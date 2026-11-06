"""``hh clients`` against a respx-mocked owner API."""

import secrets

import httpx
import pytest
import respx
from typer.testing import CliRunner

from homelab_harness_cli.main import app

runner = CliRunner()
BASE = "http://harness.test"
CIMD_ID = "cimd:claude.ai:oauth:claude-code-client-metadata"


@pytest.fixture(autouse=True)
def owner_env(monkeypatch):
    monkeypatch.setenv("HH_CLI_URL", BASE)
    monkeypatch.setenv("HH_CLI_TOKEN", f"hhmcp_{secrets.token_urlsafe(8)}")
    monkeypatch.delenv("HH_CLI_TOKEN_FILE", raising=False)


@pytest.fixture
def api():
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


def test_list_shows_oauth_and_token_clients(api):
    api.get("/api/clients").mock(
        return_value=httpx.Response(
            200,
            json={
                "clients": [
                    {
                        "id": CIMD_ID,
                        "kind": "oauth-cimd",
                        "name": "Claude Code",
                        "created_at": "2026-11-01T00:00:00Z",
                        "active": 2,
                    },
                    {
                        "id": "hh",
                        "kind": "token-owner",
                        "name": "hh",
                        "created_at": "2026-11-01T00:00:00Z",
                        "active": 0,
                    },
                ]
            },
        )
    )
    result = runner.invoke(app, ["clients", "list"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].startswith(f"{CIMD_ID}\toauth-cimd\tactive (2)")
    assert lines[0].endswith("Claude Code")
    assert "hh\ttoken-owner\trevoked" in lines[1]


def test_revoke_posts_and_reports(api):
    route = api.post(f"/api/clients/{CIMD_ID}/revoke").mock(
        return_value=httpx.Response(200, json={"id": CIMD_ID, "revoked": 2})
    )
    result = runner.invoke(app, ["clients", "revoke", CIMD_ID])
    assert result.exit_code == 0, result.output
    assert route.called
    assert f"revoked {CIMD_ID} (2)" in result.output


def test_revoke_unknown_client_fails(api):
    api.post("/api/clients/nope/revoke").mock(
        return_value=httpx.Response(404, json={"detail": "no client 'nope'"})
    )
    result = runner.invoke(app, ["clients", "revoke", "nope"])
    assert result.exit_code == 1
    assert "no client 'nope'" in result.output
