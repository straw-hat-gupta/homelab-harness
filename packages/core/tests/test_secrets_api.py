"""The owner vault API over HTTP against real Postgres, and targets that name vault secrets.

Every response is collected and searched for the planted canaries: no route may
return a value (R-34). The redactor is cleared first, so a leak cannot hide
behind masking.
"""

import asyncio
import contextlib
import json
import uuid

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from pydantic import SecretStr
from sqlalchemy import text

from homelab_harness.app import create_app
from homelab_harness.mcp.clients import ClientRole, create_client
from homelab_harness.redaction import MASK, redactor
from homelab_harness.secrets.keys import generate_kek, keyring_line
from homelab_harness.secrets.kinds import SecretKind
from homelab_harness.settings import Environment, KekProviderKind, Settings
from homelab_harness_sdk.errors import InvalidInput

KINDS = list(SecretKind)


def settings_for(url, *keks, targets_file=None):
    return Settings(
        env=Environment.TEST,
        database_url=SecretStr(url),
        secrets_kek_provider=KekProviderKind.ENV if keks else None,
        secrets_kek=SecretStr(",".join(keyring_line(k) for k in keks)) if keks else None,
        targets_file=targets_file,
    )


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


async def token_for(app, role):
    async with app.state.db_sessions.begin() as session:
        return await create_client(
            session, client_id=f"{role.value}-{uuid.uuid4().hex[:8]}", role=role
        )


class Recorder:
    """An HTTP client that keeps every response body for the leak check."""

    def __init__(self, app, token):
        self.bodies = []
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://harness",
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )

    async def __call__(self, method, path, **kwargs):
        response = await self._client.request(method, path, **kwargs)
        self.bodies.append(response.text)
        return response

    async def aclose(self):
        await self._client.aclose()


@pytest.fixture
def kek():
    return generate_kek("kek-1")


@pytest.fixture
async def app(fresh_migrated_url, kek):
    async with running(settings_for(fresh_migrated_url, kek)) as application:
        yield application


@pytest.fixture
async def owner(app):
    recorder = Recorder(app, await token_for(app, ClientRole.OWNER))
    yield recorder
    await recorder.aclose()


async def test_every_route_answers_without_values(app, owner, kind_sample):
    redactor.clear()
    canaries = []
    for kind in KINDS:
        value, fields, metadata, canary = kind_sample(kind.value)
        canaries.append(canary)
        body = {"name": f"s-{kind.value}", "kind": kind.value, "metadata": metadata}
        body |= {"value": value} if value is not None else {"fields": fields}
        created = await owner("POST", "/api/secrets", json=body)
        assert created.status_code == 201, created.text
        assert created.json()["handle"] == f"secret://s-{kind.value}"
        new_value, new_fields, _, new_canary = kind_sample(kind.value)
        canaries.append(new_canary)
        rotate = {"value": new_value} if new_value is not None else {"fields": new_fields}
        rotated = await owner("POST", f"/api/secrets/s-{kind.value}/versions", json=rotate)
        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["current_version"] == 2
        shown = await owner("GET", f"/api/secrets/s-{kind.value}")
        assert [v["version"] for v in shown.json()["versions"]] == [1, 2]

    listed = (await owner("GET", "/api/secrets")).json()["secrets"]
    assert sorted(s["name"] for s in listed) == sorted(f"s-{k.value}" for k in KINDS)
    generated = await owner(
        "POST", "/api/secrets/generate", json={"name": "deploy", "comment": "deploy@harness"}
    )
    assert generated.status_code == 201
    assert (await owner("POST", "/api/secrets/deploy/versions", json={"generate": True})).is_success
    assert (await owner("POST", "/api/secrets/s-password/revoke")).is_success
    rewrap = await owner("POST", "/api/vault/rotate-kek")
    assert rewrap.json() == {
        "kek_id": "kek-1",
        "rewrapped": 0,
        "already_current": 2 * len(KINDS) + 2,
        "failed": 0,
    }
    deleted = await owner("DELETE", "/api/secrets/s-kv", params={"confirm": "s-kv"})
    assert deleted.json() == {"name": "s-kv", "versions_destroyed": 2}
    assert (await owner("GET", "/api/secrets/s-kv")).status_code == 404

    everything = "\n".join(owner.bodies)
    for canary in canaries:
        assert canary not in everything
    assert "PRIVATE KEY" not in everything
    assert MASK not in everything  # nothing needed masking: no value was there to mask


async def test_generated_ssh_key_returns_only_the_public_half(app, owner, engine):
    response = await owner(
        "POST",
        "/api/secrets/generate",
        json={"name": "docker-01-deploy", "comment": "deploy@harness", "from_hosts": ["10.0.0.5"]},
    )
    assert response.status_code == 201
    body = response.json()
    public = serialization.load_ssh_public_key(body["public_key"].encode())
    assert body["public_key"].startswith("ssh-ed25519 ")
    assert body["authorized_keys"] == f'from="10.0.0.5" {body["public_key"]}'
    assert body["secret"]["metadata"]["fingerprint"].startswith("SHA256:")
    assert set(body) == {"secret", "public_key", "authorized_keys"}
    # The private key exists, sealed, and opens to the same public key.
    resolved = await app.state.vault.resolve(name="docker-01-deploy", consumer="test", purpose="t")
    private = serialization.load_ssh_private_key(
        resolved.fields.private_key.reveal().encode(), None
    )
    assert private.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    ) == public.public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    assert resolved.fields.private_key.reveal() not in response.text


async def test_rejected_input_is_never_echoed(owner):
    redactor.clear()
    planted = "CANARY_ECHO_" + uuid.uuid4().hex
    cases = [
        {"name": "a", "kind": "password", "value": [planted]},  # 422: wrong type
        {"name": "a", "kind": "password", "fields": planted},  # 422: not an object
        {"name": "a", "kind": "nope", "value": planted},  # 422: unknown kind
        {"name": "a", "kind": "proxmox_token", "value": planted},  # 400: not a UUID
        {"name": "a", "kind": "password", "value": planted, "extra": planted},  # 422
        {"name": "Bad Name", "kind": "password", "value": planted},  # 400
    ]
    for body in cases:
        response = await owner("POST", "/api/secrets", json=body)
        assert response.status_code in (400, 422), response.text
        assert planted not in response.text
    raw = await owner(
        "POST", "/api/secrets", content=f'{{"value": "{planted}"', headers={"content-type": "x"}
    )
    assert planted not in raw.text


async def test_errors_map_to_statuses(owner, kind_sample):
    value = kind_sample("password")[0]
    body = {"name": "dup", "kind": "password", "value": value}
    assert (await owner("POST", "/api/secrets", json=body)).status_code == 201
    assert (await owner("POST", "/api/secrets", json=body)).status_code == 409
    assert (await owner("GET", "/api/secrets/missing")).status_code == 404
    wrong = await owner("DELETE", "/api/secrets/dup", params={"confirm": "dupe"})
    assert wrong.status_code == 400
    regen = await owner("POST", "/api/secrets/dup/versions", json={"generate": True})
    assert regen.status_code == 400


async def test_only_owner_tokens_reach_the_api_and_only_mcp_tokens_reach_mcp(app):
    mcp_token = await token_for(app, ClientRole.MCP)
    owner_token = await token_for(app, ClientRole.OWNER)
    for token in (None, mcp_token, "hhmcp_unknown", owner_token[:-1]):
        client = Recorder(app, token)
        response = await client("GET", "/api/secrets")
        await client.aclose()
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
    mcp = Recorder(app, owner_token)
    response = await mcp("POST", "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    await mcp.aclose()
    assert response.status_code == 401


async def test_api_says_the_vault_is_off_without_a_kek(fresh_migrated_url):
    async with running(settings_for(fresh_migrated_url)) as application:
        client = Recorder(application, await token_for(application, ClientRole.OWNER))
        response = await client("GET", "/api/secrets")
        await client.aclose()
    assert response.status_code == 503
    assert "HH_SECRETS_KEK_PROVIDER" in response.json()["detail"]


async def test_readiness_counts_versions_awaiting_rewrap(fresh_migrated_url, kind_sample):
    old, new = generate_kek("kek-old"), generate_kek("kek-new")
    value = kind_sample("password")[0]
    async with running(settings_for(fresh_migrated_url, old)) as application:
        client = Recorder(application, await token_for(application, ClientRole.OWNER))
        await client("POST", "/api/secrets", json={"name": "p", "kind": "password", "value": value})
        await client.aclose()
    async with running(settings_for(fresh_migrated_url, new, old)) as application:
        client = Recorder(application, None)
        check = (await client("GET", "/readyz")).json()["checks"]["vault"]
        assert "1 version(s) on an older KEK" in check["detail"]
        owner = Recorder(application, await token_for(application, ClientRole.OWNER))
        assert (await owner("POST", "/api/vault/rotate-kek")).json()["rewrapped"] == 1
        check = (await client("GET", "/readyz")).json()["checks"]["vault"]
        assert "older KEK" not in check["detail"]
        await client.aclose()
        await owner.aclose()


# --- targets that name vault secrets ----------------------------------------


def targets_toml(tmp_path, handle, token_id="harness@pve!read"):  # noqa: S107 - a public id
    path = tmp_path / "targets.toml"
    path.write_text(
        f"""
[[proxmox]]
name = "home"
endpoints = ["pve1.lab.invalid"]
tls = {{ kind = "system" }}

[proxmox.credentials.read]
token_id = "{token_id}"
token_secret = "{handle}"
""",
        encoding="utf-8",
    )
    return path


async def store(url, kek, body):
    async with running(settings_for(url, kek)) as application:
        client = Recorder(application, await token_for(application, ClientRole.OWNER))
        response = await client("POST", "/api/secrets", json=body)
        await client.aclose()
    assert response.status_code == 201, response.text


async def test_targets_file_resolves_a_vault_secret_at_startup(
    fresh_migrated_url, kek, tmp_path, engine_for
):
    secret = str(uuid.uuid4())
    body = {"name": "pve-home-read", "kind": "proxmox_token", "value": secret}
    await store(fresh_migrated_url, kek, body | {"metadata": {"token_id": "harness@pve!read"}})
    path = targets_toml(tmp_path, "secret://pve-home-read")
    async with running(settings_for(fresh_migrated_url, kek, targets_file=path)) as application:
        target = application.state.mcp_service.registry.get("proxmox", "home")
        assert target.credentials["read"].secret == secret
        assert target.credentials["read"].token_id == "harness@pve!read"
        assert "proxmox:home" in (await application.state.readiness.run()).checks
        assert redactor.scrub_text(secret) == MASK
    async with engine_for(fresh_migrated_url) as conn:
        (data,) = (
            await conn.execute(text("SELECT data FROM audit_events WHERE kind = 'secret.used'"))
        ).one()
    assert data["consumer"] == "targets:proxmox/home/read"
    assert data["purpose"] == "target-credential"
    assert secret not in json.dumps(data)


@pytest.mark.parametrize(
    ("handle", "token_id", "kind", "message"),
    [
        ("secret://absent", "harness@pve!read", "proxmox_token", "does not exist"),
        ("secret://pve", "other@pve!read", "proxmox_token", "token_id differs"),
        ("secret://pve", "harness@pve!read", "kv", "single token value"),
    ],
)
async def test_targets_file_vault_errors_stop_startup(
    fresh_migrated_url, kek, tmp_path, kind_sample, handle, token_id, kind, message
):
    value, fields, metadata, _ = kind_sample(kind)
    body = {"name": "pve", "kind": kind, "metadata": metadata}
    await store(
        fresh_migrated_url,
        kek,
        body | ({"value": value} if value is not None else {"fields": fields}),
    )
    path = targets_toml(tmp_path, handle, token_id)
    with pytest.raises(InvalidInput, match=message):
        async with running(settings_for(fresh_migrated_url, kek, targets_file=path)):
            pass


async def test_targets_file_with_vault_handles_needs_the_vault(fresh_migrated_url, tmp_path):
    path = targets_toml(tmp_path, "secret://pve-home-read")
    with pytest.raises(InvalidInput, match="HH_SECRETS_KEK_PROVIDER"):
        create_app(settings_for(fresh_migrated_url, targets_file=path))


@pytest.fixture
def engine_for():
    from homelab_harness.db.engine import create_engine

    @contextlib.asynccontextmanager
    async def connect(url):
        engine = create_engine(Settings(env=Environment.TEST, database_url=SecretStr(url)))
        try:
            async with engine.connect() as conn:
                yield conn
        finally:
            await engine.dispose()

    return connect
