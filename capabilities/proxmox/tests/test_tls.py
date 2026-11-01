"""TLS verification against a real local TLS server with certificates made at test time."""

import hashlib
import logging
import re
import ssl
from pathlib import Path

import pytest

from homelab_harness_proxmox import (
    ApiToken,
    CaBundle,
    Endpoint,
    PinnedCertificate,
    ProxmoxClient,
    SystemTrust,
    TlsVerificationFailed,
)
from homelab_harness_proxmox.tls import build_ssl_context, certificate_fingerprint, pinned_context
from homelab_harness_sdk.errors import InvalidInput, TargetUnavailable

PACKAGE = Path(__file__).parents[1] / "src" / "homelab_harness_proxmox"


def _client(port: int, token: ApiToken, trust) -> ProxmoxClient:
    return ProxmoxClient(
        endpoint=Endpoint(host="127.0.0.1", port=port), token=token, trust=trust, connect_timeout=3
    )


async def test_ca_bundle_verifies_and_sends_the_token(
    pki, tls_server, token, canary_secret, caplog
):
    # Real wire, so httpx and httpcore debug logging runs too: the secret must not appear.
    caplog.set_level(logging.DEBUG)
    server = await tls_server([pki.issue()])
    async with _client(server.port, token, CaBundle(path=pki.ca_pem)) as pve:
        version = await pve.version()
    assert version.version == "9.2.1"
    head = server.requests[0].decode()
    assert f"Authorization: PVEAPIToken=harness@pve!read={canary_secret}" in head
    assert "HTTP Request" in caplog.text
    assert canary_secret not in caplog.text


async def test_ca_bundle_from_another_ca_is_refused(pki, make_pki, tls_server, token):
    other = make_pki("other")
    server = await tls_server([pki.issue()])
    async with _client(server.port, token, CaBundle(path=other.ca_pem)) as pve:
        with pytest.raises(TlsVerificationFailed) as raised:
            await pve.version()
    assert raised.value.retryable is False
    assert server.requests == []


async def test_pinned_fingerprint_accepts_the_matching_certificate(pki, tls_server, token):
    leaf = pki.issue()
    server = await tls_server([leaf])
    pin = PinnedCertificate(sha256=hashlib.sha256(leaf.der).hexdigest())
    async with _client(server.port, token, pin) as pve:
        assert (await pve.version()).release == "9.2"
    assert len(server.requests) == 1


async def test_pinned_fingerprint_mismatch_is_refused_before_any_request(pki, tls_server, token):
    server = await tls_server([pki.issue()])
    wrong = PinnedCertificate(sha256=hashlib.sha256(b"some other certificate").hexdigest())
    with pytest.raises(TlsVerificationFailed):
        async with _client(server.port, token, wrong):
            pass
    # The probe completed a handshake but no HTTP bytes (no token) were ever sent.
    assert server.connections == 1
    assert server.requests == []


async def test_pin_is_enforced_on_the_api_connection_not_just_the_probe(pki, tls_server, token):
    # The probe sees the pinned certificate; the API connection is offered another
    # certificate from the same CA. OpenSSL must reject it before the request is sent.
    pinned, impostor = pki.issue(), pki.issue()
    server = await tls_server([pinned, impostor])
    async with _client(
        server.port, token, PinnedCertificate(sha256=certificate_fingerprint(pinned.der))
    ) as pve:
        with pytest.raises(TlsVerificationFailed):
            await pve.version()
    assert server.connections == 2
    assert server.requests == []


async def test_pin_probe_maps_unreachable_node(token):
    pin = PinnedCertificate(sha256="00" * 32)
    # Port 1 on loopback is closed on CI runners and dev machines.
    with pytest.raises(TargetUnavailable) as raised:
        async with _client(1, token, pin):
            pass
    assert not isinstance(raised.value, TlsVerificationFailed)


async def test_unreadable_ca_bundle_is_invalid_input(tmp_path):
    with pytest.raises(InvalidInput):
        await build_ssl_context(
            CaBundle(path=tmp_path / "missing.pem"), host="h", port=1, connect_timeout=1
        )


async def test_every_trust_mode_yields_a_verifying_context(pki):
    leaf = pki.issue()
    contexts = [
        await build_ssl_context(SystemTrust(), host="h", port=1, connect_timeout=1),
        await build_ssl_context(CaBundle(path=pki.ca_pem), host="h", port=1, connect_timeout=1),
        pinned_context(
            PinnedCertificate(sha256=certificate_fingerprint(leaf.der)), leaf.der, host="h"
        ),
    ]
    for context in contexts:
        assert context.verify_mode is ssl.CERT_REQUIRED
        assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert contexts[1].check_hostname is True


def test_no_code_path_turns_off_verification_for_api_connections():
    # §2.1: verify=False is not a supported configuration. CERT_NONE appears only
    # in the pin probe, which sends no application data.
    for source in PACKAGE.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert not re.search(r"verify\s*=\s*False", text), source.name
        assert "_create_unverified_context" not in text, source.name
        if "CERT_NONE" in text:
            assert source.name == "tls.py"
            assert text.count("CERT_NONE") == 1


@pytest.mark.parametrize(
    "text",
    [
        "ab" * 32,
        ":".join(["AB"] * 32),
        "  " + ":".join(["ab"] * 32) + " ",
    ],
)
def test_fingerprint_forms_normalise(text):
    assert PinnedCertificate(sha256=text).sha256 == ":".join(["AB"] * 32)


@pytest.mark.parametrize("text", ["", "ab" * 31, "zz" * 32, "ab" * 33])
def test_malformed_fingerprints_are_rejected(text):
    with pytest.raises(ValueError, match="SHA-256"):
        PinnedCertificate(sha256=text)
