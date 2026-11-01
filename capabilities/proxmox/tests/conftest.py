"""Shared fixtures for the Proxmox capability tests.

Secrets and TLS keys are generated at run time. Nothing secret-shaped is
committed, because CI scans the whole history with gitleaks.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import ipaddress
import json
import secrets
import ssl
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import respx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from homelab_harness_proxmox import ApiToken, Endpoint, ProxmoxClient, SystemTrust

FIXTURES = Path(__file__).parent / "fixtures" / "pve-9.2"
HOST = "pve1.lab.invalid"
BASE = f"https://{HOST}:8006/api2/json"
FROZEN_NOW = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.UTC)


def fixture(name: str) -> dict[str, Any]:
    """Load ``fixtures/pve-9.2/<name>.json``."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def load() -> Callable[[str], dict[str, Any]]:
    """The fixture loader, for tests (conftest is not importable as a module)."""
    return fixture


@pytest.fixture
def canary_secret() -> str:
    """A token secret generated per test; its value never exists in the repo."""
    return f"CANARY_{secrets.token_hex(16)}"


@pytest.fixture
def token(canary_secret: str) -> ApiToken:
    return ApiToken(user="harness@pve", token_id="read", secret=canary_secret)


@pytest.fixture
def pve_mock() -> respx.MockRouter:
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


@pytest.fixture
async def pve(pve_mock: respx.MockRouter, token: ApiToken) -> AsyncIterator[ProxmoxClient]:
    """A client against the mocked API (system trust: respx replaces the network)."""
    client = ProxmoxClient(
        endpoint=Endpoint(host=HOST), token=token, trust=SystemTrust(), clock=lambda: FROZEN_NOW
    )
    async with client:
        yield client


# -- TLS material and a minimal HTTPS server for the pinning tests -------------------


@dataclass
class Issued:
    cert_pem: Path
    key_pem: Path
    der: bytes


@dataclass
class Pki:
    """A throwaway CA that issues 127.0.0.1 server certificates into ``tmp_path``."""

    directory: Path
    key: ec.EllipticCurvePrivateKey = field(
        default_factory=lambda: ec.generate_private_key(ec.SECP256R1())
    )
    cert: x509.Certificate | None = None
    _count: int = 0

    def __post_init__(self) -> None:
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test PVE Cluster CA")])
        now = dt.datetime.now(dt.UTC)
        self.cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(self.key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=False,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(self.key.public_key()), critical=False
            )
            .sign(self.key, hashes.SHA256())
        )

    @property
    def ca_pem(self) -> Path:
        path = self.directory / "ca.pem"
        assert self.cert is not None
        path.write_bytes(self.cert.public_bytes(serialization.Encoding.PEM))
        return path

    def issue(self) -> Issued:
        assert self.cert is not None
        self._count += 1
        key = ec.generate_private_key(ec.SECP256R1())
        now = dt.datetime.now(dt.UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]))
            .issuer_name(self.cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=30))
            .add_extension(
                x509.SubjectAlternativeName(
                    [x509.IPAddress(ipaddress.ip_address("127.0.0.1")), x509.DNSName("localhost")]
                ),
                critical=False,
            )
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(self.key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
            )
            .sign(self.key, hashes.SHA256())
        )
        cert_pem = self.directory / f"leaf{self._count}.pem"
        key_pem = self.directory / f"leaf{self._count}.key"
        cert_pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_pem.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        return Issued(
            cert_pem=cert_pem, key_pem=key_pem, der=cert.public_bytes(serialization.Encoding.DER)
        )


@pytest.fixture
def pki(tmp_path: Path) -> Pki:
    return Pki(directory=tmp_path)


@pytest.fixture
def make_pki(tmp_path: Path) -> Callable[[str], Pki]:
    """Another, unrelated CA (for "wrong CA" cases)."""

    def make(name: str) -> Pki:
        directory = tmp_path / name
        directory.mkdir()
        return Pki(directory=directory)

    return make


def server_context(issued: Issued) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(issued.cert_pem, issued.key_pem)
    return context


@dataclass
class TlsServer:
    """Serves ``GET /api2/json/version`` over TLS on 127.0.0.1.

    Connection *n* uses ``certificates[min(n, last)]``, so a test can present one
    certificate to the pin probe and a different one to the API connection.

    Attributes:
        requests: Raw HTTP request heads received, one per completed request.
        connections: TCP connections accepted.
    """

    certificates: list[Issued]
    requests: list[bytes] = field(default_factory=list[bytes])
    connections: int = 0
    port: int = 0
    _server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        index = min(self.connections, len(self.certificates) - 1)
        self.connections += 1
        try:
            await writer.start_tls(server_context(self.certificates[index]))
            head = await reader.readuntil(b"\r\n\r\n")
            self.requests.append(head)
            body = json.dumps(fixture("version/ok")).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )
            await writer.drain()
        except (ssl.SSLError, OSError, asyncio.IncompleteReadError):
            # The client refused our certificate or closed after the probe handshake.
            pass
        finally:
            writer.close()
            with contextlib.suppress(ssl.SSLError, OSError):
                await writer.wait_closed()


@pytest.fixture
async def tls_server() -> AsyncIterator[Callable[[list[Issued]], Any]]:
    servers: list[TlsServer] = []

    async def start(certificates: list[Issued]) -> TlsServer:
        server = TlsServer(certificates=certificates)
        await server.start()
        servers.append(server)
        return server

    yield start
    for server in servers:
        await server.stop()
