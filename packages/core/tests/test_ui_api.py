"""The UI's read façade over HTTP: real Postgres for tokens and audit, Proxmox mocked with respx.

The Proxmox capability is loaded through its entry point, as in production; core
never imports it.
"""

import asyncio
import contextlib
import json
import secrets
import uuid
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import SecretStr

from homelab_harness.app import create_app
from homelab_harness.audit.queries import recent_events
from homelab_harness.mcp.clients import ClientRole, create_client
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


@contextlib.asynccontextmanager
async def running(settings):
    application = create_app(settings)
    # The lifespan's task group must be entered and exited by one task (see test_mcp.py).
    started, stop = asyncio.Event(), asyncio.Event()

    async def serve():
        async with application.router.lifespan_context(application):
            started.set()
            await stop.wait()

    runner = asyncio.create_task(serve())
    await asyncio.wait({runner, asyncio.create_task(started.wait())}, return_when="FIRST_COMPLETED")
    if runner.done():
        runner.result()
    try:
        yield application
    finally:
        stop.set()
        await runner
        redactor.clear()


@pytest.fixture
async def app(migrated_url, targets_file):
    settings = Settings(
        env=Environment.TEST, database_url=SecretStr(migrated_url), targets_file=targets_file
    )
    async with running(settings) as application:
        yield application


async def token_for(app, role):
    client_id = f"{role.value}-{uuid.uuid4().hex[:8]}"
    async with app.state.db_sessions.begin() as session:
        return client_id, await create_client(session, client_id=client_id, role=role)


@pytest.fixture
async def owner(app):
    return await token_for(app, ClientRole.OWNER)


@pytest.fixture
def pve_mock():
    with respx.mock(base_url=PVE, assert_all_called=False) as router:
        yield router


def http(app, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://harness", headers=headers
    )


async def ui_events(app, client_id):
    async with app.state.db_sessions() as session:
        events = await recent_events(session, limit=50)
    return [e for e in events if e.actor == f"client:{client_id}" and e.kind == "ui.read"]


async def test_tree_lists_nodes_guests_and_storages_and_is_audited(
    app, owner, pve_mock, pve_secret
):
    client_id, token = owner
    pve_mock.get("/cluster/resources").mock(
        return_value=httpx.Response(200, json=fixture("cluster-resources/ok"))
    )
    async with http(app, token) as client:
        response = await client.get("/api/ui/tree")
    assert response.status_code == 200
    body = response.json()
    (cluster,) = body["clusters"]
    assert cluster["id"] == "home"
    assert cluster["reachable"] is True
    assert [n["name"] for n in cluster["nodes"]] == ["pve1", "pve2"]
    pve1 = cluster["nodes"][0]
    assert [g["id"] for g in pve1["guests"]] == ["home:101", "home:9000"]
    assert pve1["guests"][0]["name"] == "web-01"
    assert [s["id"] for s in cluster["storages"]] == ["home:pve1:local-zfs"]
    # The read credential reaches Proxmox, never the browser.
    assert pve_mock.calls.last.request.headers["Authorization"].endswith(pve_secret)
    assert pve_secret not in response.text

    (event,) = await ui_events(app, client_id)
    assert event.target == "home"
    assert event.data["view"] == "tree"
    assert event.data["tools"] == ["proxmox.cluster.resources"]
    assert event.data["outcome"] == "ok"


async def test_tree_lists_an_unreachable_cluster_with_a_safe_error(app, owner, pve_mock):
    _, token = owner
    body = f"CANARY_BODY_{secrets.token_hex(8)}"
    pve_mock.get("/cluster/resources").mock(
        return_value=httpx.Response(500, json={"message": body})
    )
    async with http(app, token) as client:
        response = await client.get("/api/ui/tree")
    assert response.status_code == 200
    (cluster,) = response.json()["clusters"]
    assert cluster["reachable"] is False
    assert cluster["error"]
    assert body not in response.text


async def test_node_summary(app, owner, pve_mock):
    client_id, token = owner
    pve_mock.get("/nodes/pve1/status").mock(
        return_value=httpx.Response(200, json=fixture("node-status/ok"))
    )
    async with http(app, token) as client:
        response = await client.get("/api/ui/objects/node/home:pve1/summary")
    assert response.status_code == 200
    summary = response.json()
    assert summary["type"] == "node"
    assert summary["id"] == "home:pve1"
    stats = {s["key"]: s for s in summary["stats"]}
    assert stats["cpu"]["value"] == 8.0
    assert stats["memory"]["max"] == 68719476736
    (event,) = await ui_events(app, client_id)
    assert event.data["view"] == "summary"
    assert event.data["tools"] == ["proxmox.node.get"]


async def test_guest_summary_masks_config(app, owner, pve_mock):
    _, token = owner
    planted = f"CANARY_CIPW_{secrets.token_hex(8)}"
    config = fixture("qemu-config/ok")
    config["data"].update({"cipassword": planted})
    pve_mock.get("/cluster/resources").mock(
        return_value=httpx.Response(200, json=fixture("cluster-resources/ok"))
    )
    pve_mock.get("/nodes/pve1/qemu/101/status/current").mock(
        return_value=httpx.Response(200, json=fixture("qemu-status/ok"))
    )
    pve_mock.get("/nodes/pve1/qemu/101/config").mock(return_value=httpx.Response(200, json=config))
    async with http(app, token) as client:
        response = await client.get("/api/ui/objects/qemu/home:101/summary")
    assert response.status_code == 200
    assert planted not in response.text
    props = {p["label"]: p for p in response.json()["properties"]}
    assert props["config: cipassword"] == {
        "label": "config: cipassword",
        "value": "[MASKED]",
        "untrusted": True,
    }


async def test_storage_and_datacenter_summaries(app, owner, pve_mock):
    _, token = owner
    pve_mock.get("/nodes/pve1/storage/local-zfs/status").mock(
        return_value=httpx.Response(200, json=fixture("storage-status/ok"))
    )
    pve_mock.get("/cluster/status").mock(
        return_value=httpx.Response(200, json=fixture("cluster-status/ok"))
    )
    pve_mock.get("/version").mock(return_value=httpx.Response(200, json=fixture("version/ok")))
    async with http(app, token) as client:
        storage = await client.get("/api/ui/objects/storage/home:pve1:local-zfs/summary")
        datacenter = await client.get("/api/ui/objects/datacenter/home/summary")
    assert storage.status_code == 200
    assert storage.json()["stats"][0]["max"] == 1000204886016
    assert datacenter.status_code == 200
    assert [c["id"] for c in datacenter.json()["children"]] == ["home:pve1", "home:pve2"]


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("/api/ui/objects/node/home/summary", 400),  # malformed id
        ("/api/ui/objects/qemu/home:42/summary", 400),  # VMID out of range
        ("/api/ui/objects/node/other:pve1/summary", 400),  # unknown cluster
        ("/api/ui/objects/zfs/home:pve1/summary", 422),  # unknown object type
    ],
)
async def test_bad_object_references_are_rejected_before_any_target_call(
    app, owner, pve_mock, path, code
):
    _, token = owner
    async with http(app, token) as client:
        response = await client.get(path)
    assert response.status_code == code
    assert not pve_mock.calls


async def test_target_errors_are_mapped_and_audited(app, owner, pve_mock):
    client_id, token = owner
    body = f"CANARY_BODY_{secrets.token_hex(8)}"
    pve_mock.get("/nodes/pve1/status").mock(
        return_value=httpx.Response(500, json={"message": body})
    )
    async with http(app, token) as client:
        response = await client.get("/api/ui/objects/node/home:pve1/summary")
    assert response.status_code == 502
    assert body not in response.text
    (event,) = await ui_events(app, client_id)
    assert event.data["outcome"] == "error"
    assert event.data["error_type"]


@pytest.mark.parametrize("path", ["/api/ui/tree", "/api/ui/objects/node/home:pve1/summary"])
async def test_facade_needs_an_owner_token(app, pve_mock, path):
    _, mcp_token = await token_for(app, ClientRole.MCP)
    async with http(app) as anonymous, http(app, mcp_token) as agent:
        missing = await anonymous.get(path)
        wrong_role = await agent.get(path)
    assert missing.status_code == 401
    assert wrong_role.status_code == 401
    assert not pve_mock.calls


async def test_a_failed_audit_write_returns_no_data(app, owner, pve_mock, monkeypatch):
    _, token = owner
    pve_mock.get("/cluster/resources").mock(
        return_value=httpx.Response(200, json=fixture("cluster-resources/ok"))
    )

    async def broken(**_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(app.state.audit, "record", broken)
    async with http(app, token) as client:
        response = await client.get("/api/ui/tree")
    assert response.status_code == 503
    assert "web-01" not in response.text
