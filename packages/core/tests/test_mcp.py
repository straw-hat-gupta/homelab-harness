"""End to end over HTTP: the MCP SDK's client against the ASGI app, Proxmox mocked with respx.

Real Postgres (testcontainers) holds the client tokens and the audit log. The
Proxmox capability is loaded through its entry point, as in production.
"""

import asyncio
import json
import secrets
import uuid
from pathlib import Path

import httpx
import httpx2
import pytest
import respx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from pydantic import SecretStr
from sqlalchemy import text

from homelab_harness.app import create_app
from homelab_harness.audit.queries import recent_events
from homelab_harness.mcp.clients import create_client, revoke_client
from homelab_harness.mcp.results import META_AS_OF, META_UNTRUSTED, UNTRUSTED_NOTICE
from homelab_harness.redaction import redactor
from homelab_harness.settings import Environment, Settings

FIXTURES = Path(__file__).parents[3] / "capabilities" / "proxmox" / "tests" / "fixtures" / "pve-9.2"
PVE = "https://pve1.lab.invalid:8006/api2/json"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def pve_secret():
    return f"CANARY_PVE_{secrets.token_hex(12)}"


@pytest.fixture
def targets_file(tmp_path, pve_secret):
    secret = tmp_path / "pve-home-read"
    secret.write_text(pve_secret + "\n", encoding="utf-8")
    secret.chmod(0o400)
    path = tmp_path / "targets.toml"
    path.write_text(
        f"""
[[proxmox]]
name = "home"
endpoints = ["pve1.lab.invalid"]
tls = {{ kind = "system" }}

[proxmox.credentials.read]
token_id = "harness@pve!read"
token_secret_file = "{secret}"
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
async def app(migrated_url, targets_file):
    settings = Settings(
        env=Environment.TEST, database_url=SecretStr(migrated_url), targets_file=targets_file
    )
    application = create_app(settings)
    # The MCP transport's lifespan holds an anyio task group, which must be entered
    # and exited by the same task; pytest-asyncio runs fixture setup and teardown
    # in different tasks, so the lifespan runs in a task of its own.
    started, stop = asyncio.Event(), asyncio.Event()

    async def serve():
        async with application.router.lifespan_context(application):
            started.set()
            await stop.wait()

    runner = asyncio.create_task(serve())
    await asyncio.wait({runner, asyncio.create_task(started.wait())}, return_when="FIRST_COMPLETED")
    if runner.done():
        runner.result()  # startup failed: raise its error here
    yield application
    stop.set()
    await runner
    redactor.clear()


@pytest.fixture
def client_id():
    return f"test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def token(app, client_id):
    async with app.state.db_sessions.begin() as session:
        return await create_client(session, client_id=client_id)


@pytest.fixture
def pve_mock():
    with respx.mock(base_url=PVE, assert_all_called=False) as router:
        yield router


def http(app, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://harness", headers=headers
    )


def mcp_client(app, token, mode="auto"):
    transport = streamable_http_client("http://harness/mcp", http_client=http(app, token))
    return Client(transport, mode=mode, cache=None)


async def audit_rows(app, client_id):
    async with app.state.db_sessions() as session:
        events = await recent_events(session, limit=50)
    return [e for e in events if e.actor == f"client:{client_id}"]


@pytest.mark.parametrize("mode", ["2026-07-28", "legacy"])
async def test_list_tools_shows_proxmox_tools_with_annotations(app, token, mode):
    async with mcp_client(app, token, mode) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert len([n for n in tools if n.startswith("proxmox.")]) == 18
    guest = tools["proxmox.guest.get"]
    assert guest.annotations.read_only_hint is True
    assert guest.annotations.idempotent_hint is True
    assert guest.annotations.destructive_hint is False
    assert guest.annotations.open_world_hint is False
    assert guest.input_schema["type"] == "object"
    assert "as_of" in guest.output_schema["properties"]
    assert guest.description


@pytest.mark.parametrize("mode", ["2026-07-28", "legacy"])
async def test_tool_call_returns_structured_result_and_is_audited(
    app, token, client_id, pve_mock, pve_secret, mode
):
    pve_mock.get("/cluster/resources").mock(
        return_value=httpx.Response(200, json=fixture("cluster-resources/ok"))
    )
    async with mcp_client(app, token, mode) as client:
        result = await client.call_tool("proxmox.cluster.resources", {"tag": "harness"})
    assert result.is_error is False
    data = result.structured_content
    assert data["cluster"] == "home"
    assert data["as_of"]
    assert data["resources"][0]["untrusted"]["name"] == "web-01"
    assert result.meta[META_UNTRUSTED] is True
    assert result.meta[META_AS_OF] == data["as_of"]
    assert UNTRUSTED_NOTICE in result.content[0].text
    # The token travels to Proxmox but never back to the client.
    sent = pve_mock.calls.last.request.headers["Authorization"]
    assert sent == f"PVEAPIToken=harness@pve!read={pve_secret}"
    assert pve_secret not in json.dumps(data)
    assert pve_secret not in result.content[0].text

    (event,) = (await audit_rows(app, client_id))[:1]
    assert event.kind == "mcp.tool_call"
    assert event.target == "home"
    assert event.data["tool"] == "proxmox.cluster.resources"
    assert event.data["outcome"] == "ok"
    assert isinstance(event.data["duration_ms"], int)
    assert "harness" not in json.dumps(event.data)  # arguments are not recorded


async def test_guest_config_is_masked_end_to_end(app, token, pve_mock):
    planted = f"CANARY_CIPW_{secrets.token_hex(8)}"
    config = fixture("qemu-config/ok")
    config["data"].update({"cipassword": planted, "args": planted, "apitoken": planted})
    pve_mock.get("/nodes/pve1/qemu/101/status/current").mock(
        return_value=httpx.Response(200, json=fixture("qemu-status/ok"))
    )
    pve_mock.get("/nodes/pve1/qemu/101/config").mock(return_value=httpx.Response(200, json=config))
    async with mcp_client(app, token) as client:
        result = await client.call_tool(
            "proxmox.guest.get", {"vmid": 101, "node": "pve1", "type": "qemu"}
        )
    assert result.is_error is False
    body = json.dumps(result.structured_content) + result.content[0].text
    assert planted not in body
    masked = result.structured_content["untrusted"]["config"]
    assert masked["cipassword"] == masked["args"] == masked["apitoken"] == "[MASKED]"


async def test_target_error_becomes_a_safe_tool_error(app, token, client_id, pve_mock):
    body = f"CANARY_BODY_{secrets.token_hex(8)}"
    pve_mock.get("/nodes").mock(
        return_value=httpx.Response(
            500, json={"message": body}, extensions={"reason_phrase": body.encode()}
        )
    )
    async with mcp_client(app, token) as client:
        result = await client.call_tool("proxmox.node.list", {})
    assert result.is_error is True
    message = result.content[0].text
    assert "HTTP 500" in message
    assert body not in message
    (event,) = (await audit_rows(app, client_id))[:1]
    assert event.data["outcome"] == "error"
    assert event.data["error_type"] == "TargetUnavailable"


async def test_invalid_arguments_name_fields_not_values(app, token, client_id):
    async with mcp_client(app, token) as client:
        result = await client.call_tool("proxmox.guest.get", {"vmid": "CANARY_ARG", "extra": 1})
    assert result.is_error is True
    assert "invalid arguments for proxmox.guest.get" in result.content[0].text
    assert "CANARY_ARG" not in result.content[0].text
    (event,) = (await audit_rows(app, client_id))[:1]
    assert event.data["error_type"] == "InvalidInput"


async def test_unknown_tool_is_a_protocol_error(app, token):
    async with mcp_client(app, token) as client:
        with pytest.raises(MCPError, match="unknown tool"):
            await client.call_tool("proxmox.guest.destroy", {})


async def test_missing_or_wrong_token_gets_401_with_www_authenticate(app, token):
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    for presented in (None, "hhmcp_not-a-real-token", token[:-1]):
        async with http(app, presented) as client:
            response = await client.post("/mcp", json=request)
        assert response.status_code == 401
        assert response.headers["www-authenticate"].startswith("Bearer ")


async def test_revoked_token_gets_401(app, token, client_id):
    async with mcp_client(app, token) as client:
        await client.list_tools()
    async with app.state.db_sessions.begin() as session:
        await revoke_client(session, client_id=client_id)
    async with http(app, token) as client:
        response = await client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
    assert response.status_code == 401


async def test_only_the_token_hash_is_stored(app, token, client_id, engine):
    async with engine.connect() as conn:
        stored = await conn.scalar(
            text("SELECT token_hash FROM mcp_clients WHERE client_id = :c"), {"c": client_id}
        )
    assert stored != token
    assert len(stored) == 64
    assert token not in stored


async def test_readiness_reports_each_target_without_failing(app, pve_mock):
    route = pve_mock.get("/version")
    route.mock(return_value=httpx.Response(200, json=fixture("version/ok")))
    async with http(app) as client:
        ok = (await client.get("/readyz")).json()
        route.mock(return_value=httpx.Response(401))
        degraded = await client.get("/readyz")
    assert ok["checks"]["proxmox:home"] == {"status": "ok", "detail": ""}
    assert degraded.status_code == 200
    assert degraded.json()["checks"]["proxmox:home"] == {
        "status": "degraded",
        "detail": "AuthRejected",
    }


async def test_audit_failure_fails_the_call_closed(app, token, pve_mock):
    pve_mock.get("/nodes").mock(return_value=httpx.Response(200, json=fixture("nodes/ok")))

    class BrokenAudit:
        async def record(self, **_kwargs):
            raise RuntimeError("database down")

    app.state.audit = BrokenAudit()
    async with mcp_client(app, token) as client:
        result = await client.call_tool("proxmox.node.list", {})
    assert result.is_error is True
    assert "audit" in result.content[0].text
    assert result.structured_content is None
