"""Serving the built UI: cache headers, CSP, and an SPA fallback that never shadows the server."""

import httpx
import pytest

from homelab_harness.app import create_app
from homelab_harness.settings import Environment, Settings
from homelab_harness.ui.static import CONTENT_SECURITY_POLICY
from homelab_harness_sdk.errors import InvalidInput

INDEX = "<!doctype html><title>homelab-harness</title><div id=root></div>"


@pytest.fixture
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX, encoding="utf-8")
    (root / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (root / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("not part of the build", encoding="utf-8")
    return root


@pytest.fixture
async def client(dist):
    app = create_app(Settings(env=Environment.TEST, ui_dir=dist))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://harness"
    ) as c:
        yield c


@pytest.mark.parametrize("path", ["/", "/objects/node/home:pve1", "/objects/qemu/home:101?tab=x"])
async def test_client_routes_get_the_app_shell_uncached_with_a_strict_csp(client, path):
    response = await client.get(path)
    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert "script-src 'self'" in CONTENT_SECURITY_POLICY
    script_src = next(d for d in CONTENT_SECURITY_POLICY.split("; ") if d.startswith("script-src"))
    assert script_src == "script-src 'self'"
    assert "unsafe-eval" not in CONTENT_SECURITY_POLICY
    assert "frame-ancestors 'none'" in CONTENT_SECURITY_POLICY
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_hashed_assets_are_immutable(client):
    response = await client.get("/assets/index-abc123.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


async def test_other_build_files_are_served_uncached(client):
    response = await client.get("/favicon.svg")
    assert response.status_code == 200
    assert response.text == "<svg/>"
    assert response.headers["cache-control"] == "no-cache"


async def test_a_missing_asset_is_a_404_not_the_shell(client):
    response = await client.get("/assets/index-gone.js")
    assert response.status_code == 404
    assert INDEX not in response.text


async def test_paths_outside_the_build_are_never_served(client):
    response = await client.get("/..%2Foutside.txt")
    assert "not part of the build" not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/nope",
        "/api/ui/nope",
        "/mcpx/../mcp/nope",
        "/healthz/extra",
        "/readyz/extra",
        "/docs/extra",
        "/.well-known/oauth-authorization-server",
        "/oauth/nope",
        "/owner/nope",
        "/owner/static/nope.css",
    ],
)
async def test_server_prefixes_never_fall_back_to_the_shell(client, path):
    response = await client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert INDEX not in response.text


async def test_server_routes_still_win(client):
    health = await client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    openapi = await client.get("/openapi.json")
    assert openapi.status_code == 200
    assert "/api/ui/tree" in openapi.json()["paths"]
    # The UI routes need an owner token: the fallback does not answer for them.
    tree = await client.get("/api/ui/tree")
    assert tree.status_code == 401
    assert "content-security-policy" not in tree.headers


async def test_no_ui_is_served_without_a_build_directory():
    app = create_app(Settings(env=Environment.TEST))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://harness"
    ) as c:
        assert (await c.get("/")).status_code == 404


def test_a_build_directory_without_index_html_stops_startup(tmp_path):
    with pytest.raises(InvalidInput, match=r"index\.html"):
        create_app(Settings(env=Environment.TEST, ui_dir=tmp_path))


async def test_auth_routes_are_not_shadowed_by_the_shell(dist):
    app = create_app(
        Settings(env=Environment.TEST, ui_dir=dist, public_url="http://localhost:8080")
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8080"
    ) as c:
        metadata = await c.get("/.well-known/oauth-authorization-server")
        resource = await c.get("/.well-known/oauth-protected-resource/mcp")
        login = await c.get("/owner/login")
        authorize = await c.get("/oauth/authorize")
    assert metadata.status_code == 200
    assert metadata.json()["issuer"].startswith("http://localhost:8080")
    assert resource.status_code == 200
    for response in (login, authorize):
        assert INDEX not in response.text
