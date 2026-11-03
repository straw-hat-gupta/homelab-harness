"""Shared fixtures: one real Postgres per test session (testcontainers).

Services test against real Postgres, never a mocked store (R-01). Without
Docker the database tests are skipped with a clear reason, except in CI, where
a missing Docker daemon fails the run instead of silently skipping half the suite.
"""

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import secrets
import struct
import uuid

import cbor2
import docker
import psycopg
import pytest
from alembic import command
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from testcontainers.community.postgres import PostgresContainer

from homelab_harness.db.engine import create_engine, create_session_factory
from homelab_harness.db.migrate import alembic_config
from homelab_harness.settings import Environment, Settings

POSTGRES_IMAGE = "postgres:17-alpine"


def _docker_problem():
    try:
        docker.from_env().ping()
    except Exception as exc:
        return type(exc).__name__
    return None


def _libpq_url(url):
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def libpq_url():
    """Convert a SQLAlchemy URL to one plain psycopg accepts (no driver suffix)."""
    return _libpq_url


@pytest.fixture(scope="session")
def postgres_url():
    problem = _docker_problem()
    if problem is not None:
        if os.environ.get("CI"):
            pytest.fail(f"Docker is required for the database tests in CI ({problem})")
        pytest.skip(f"Docker is unavailable ({problem}); database tests need it")
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def migrated_url(postgres_url):
    command.upgrade(alembic_config(postgres_url), "head")
    return postgres_url


@pytest.fixture
def empty_database_url(postgres_url):
    """A fresh, empty database in the shared container, dropped afterwards."""
    name = f"t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_libpq_url(postgres_url), autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    yield make_url(postgres_url).set(database=name).render_as_string(hide_password=False)
    with psycopg.connect(_libpq_url(postgres_url), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture
def db_settings(migrated_url):
    return Settings(env=Environment.TEST, database_url=SecretStr(migrated_url))


@pytest.fixture
async def engine(db_settings):
    eng = create_engine(db_settings)
    yield eng
    await eng.dispose()


@pytest.fixture
def sessions(engine):
    return create_session_factory(engine)


@pytest.fixture
def fresh_migrated_url(empty_database_url):
    """A fresh database at head, for tests that touch every row (KEK rotation)."""
    command.upgrade(alembic_config(empty_database_url), "head")
    return empty_database_url


def _ssh_private_key():
    return (
        Ed25519PrivateKey.generate()
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption(),
        )
        .decode()
    )


def _canary(label):
    return f"CANARY_{label}_{secrets.token_hex(10)}"


def _kind_sample(kind):
    match kind:
        case "ssh_key":
            pem = _ssh_private_key()
            return pem, None, {"comment": "test@harness"}, pem.splitlines()[1]
        case "password":
            value = _canary("PW")
            return value, None, {"username": "root", "target": "pve1.lab.invalid"}, value
        case "api_token":
            value = _canary("API")
            meta = {"scheme": "bearer", "allowed_base_urls": ["https://api.example.invalid"]}
            return value, None, meta, value
        case "proxmox_token":
            value = str(uuid.uuid4())
            return value, None, {"token_id": "harness@pve!read", "cluster": "home"}, value
        case "cloudflare_token":
            value = _canary("CF")
            return value, None, {"scope": "zone:example.invalid"}, value
        case "github_token":
            value = _canary("GH")
            meta = {"repos": ["owner/vault"], "permissions": ["contents:write"]}
            return value, None, meta, value
        case "file":
            value = _canary("FILE")
            content = base64.b64encode(f"token: {value}\n".encode()).decode()
            return None, {"content": content}, {"filename": "kubeconfig"}, value
        case "kv":
            value = _canary("KV")
            return None, {"values": {"API_KEY": value, "OTHER": _canary("KV2")}}, {}, value
    raise AssertionError(kind)


@pytest.fixture
def kind_sample():
    """Factory: kind -> (value, fields, metadata, canary), API-shaped, canaries made at runtime."""
    return _kind_sample


def _b64u(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class SoftAuthenticator:
    """A software passkey: real P-256 keys and WebAuthn encodings, so py_webauthn verifies it.

    Registration uses the ``none`` attestation format; assertions are signed over
    ``authenticatorData || SHA-256(clientDataJSON)`` as the spec requires.
    """

    def __init__(self, *, origin, user_verified=True):
        self.origin = origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(32)
        self.sign_count = 0
        self.flags_uv = 0x04 if user_verified else 0

    def _cose_key(self):
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps(
            {
                1: 2,
                3: -7,
                -1: 1,
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )

    def _client_data(self, kind, challenge, origin):
        data = {"type": kind, "challenge": challenge, "origin": origin or self.origin}
        return json.dumps({**data, "crossOrigin": False}).encode()

    def register(self, options, *, origin=None):
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        rp_hash = hashlib.sha256(options["rp"]["id"].encode()).digest()
        auth_data = (
            rp_hash
            + bytes([0x01 | self.flags_uv | 0x40])  # user present, verified, attested data
            + struct.pack(">I", 0)
            + bytes(16)  # AAGUID
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self._cose_key()
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": _b64u(self.credential_id),
            "rawId": _b64u(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64u(client_data),
                "attestationObject": _b64u(attestation),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
        }

    def assertion(self, options, *, origin=None, tamper=False):
        self.sign_count += 1
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        rp_hash = hashlib.sha256(options["rpId"].encode()).digest()
        auth_data = rp_hash + bytes([0x01 | self.flags_uv]) + struct.pack(">I", self.sign_count)
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        if tamper:
            signature = signature[:-1] + bytes([signature[-1] ^ 1])
        return {
            "id": _b64u(self.credential_id),
            "rawId": _b64u(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64u(client_data),
                "authenticatorData": _b64u(auth_data),
                "signature": _b64u(signature),
                "userHandle": None,
            },
            "clientExtensionResults": {},
        }


@pytest.fixture
def soft_authenticator():
    """The software passkey class: ``soft_authenticator(origin=...)``."""
    return SoftAuthenticator


@pytest.fixture
def serve_app():
    """Run an app's lifespan in a task of its own (the MCP transport needs one task).

    Usage: ``async with serve_app(app): ...``.
    """

    @contextlib.asynccontextmanager
    async def serve(application):
        started, stop = asyncio.Event(), asyncio.Event()

        async def run():
            async with application.router.lifespan_context(application):
                started.set()
                await stop.wait()

        runner = asyncio.create_task(run())
        waiter = asyncio.create_task(started.wait())
        await asyncio.wait({runner, waiter}, return_when="FIRST_COMPLETED")
        if runner.done():
            waiter.cancel()
            runner.result()
        try:
            yield application
        finally:
            stop.set()
            await runner

    return serve
