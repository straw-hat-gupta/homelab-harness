"""TLS trust for Proxmox endpoints: CA bundle, pinned fingerprint, or system store.

Verification is never optional (§2.1). There is deliberately no "insecure" mode.

Pinning a SHA-256 fingerprint works in two steps, so that the API connection
itself is verified by OpenSSL rather than checked after the fact:

1. A *probe* handshake fetches the node's certificate. It sends no HTTP bytes,
   so no credential is exposed even to an impostor. Its certificate is accepted
   only if its SHA-256 digest equals the pin (constant-time compare).
2. That exact certificate becomes the **only** trust anchor of the context the
   API client uses (``VERIFY_X509_PARTIAL_CHAIN`` lets a leaf be an anchor).
   Every later connection must present it, or the handshake fails before the
   ``Authorization`` header is sent.

Checking the fingerprint after an httpx request instead would already have sent
the token over the unverified connection; a custom transport would need httpx
internals. The probe-then-anchor approach needs neither.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import ssl
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from homelab_harness_proxmox.errors import TlsVerificationFailed
from homelab_harness_sdk.errors import InvalidInput, TargetUnavailable


class SystemTrust(BaseModel):
    """Trust the system CA store: for nodes with ACME or other public certificates."""

    model_config = ConfigDict(frozen=True)
    kind: Literal["system"] = "system"


class CaBundle(BaseModel):
    """Trust a CA file, usually the cluster CA ``/etc/pve/pve-root-ca.pem``."""

    model_config = ConfigDict(frozen=True)
    kind: Literal["ca_bundle"] = "ca_bundle"
    path: Path


class PinnedCertificate(BaseModel):
    """Trust exactly one certificate, identified by its SHA-256 fingerprint.

    Attributes:
        sha256: The fingerprint as PVE shows it (``AB:CD:…``) or as plain hex;
            normalised to upper-case colon-separated form.
    """

    model_config = ConfigDict(frozen=True)
    kind: Literal["pinned"] = "pinned"
    sha256: str

    @field_validator("sha256")
    @classmethod
    def _normalise(cls, value: str) -> str:
        hexdigits = value.replace(":", "").strip().upper()
        if len(hexdigits) != 64 or any(c not in "0123456789ABCDEF" for c in hexdigits):
            raise ValueError("expected a SHA-256 fingerprint: 64 hex digits")
        return ":".join(hexdigits[i : i + 2] for i in range(0, 64, 2))

    @property
    def digest(self) -> bytes:
        """The fingerprint as 32 raw bytes."""
        return bytes.fromhex(self.sha256.replace(":", ""))


TlsTrust = Annotated[SystemTrust | CaBundle | PinnedCertificate, Field(discriminator="kind")]


def certificate_fingerprint(der: bytes) -> str:
    """Return the SHA-256 fingerprint of a DER certificate in PVE's display form."""
    return PinnedCertificate(sha256=hashlib.sha256(der).hexdigest()).sha256


def _base_context(*, cafile: str | None = None, cadata: bytes | None = None) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=cafile, cadata=cadata)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


async def fetch_peer_certificate(host: str, port: int, *, connect_timeout: float) -> bytes:
    """Complete a TLS handshake and return the server's certificate (DER) unverified.

    The caller must compare the result with a pin before trusting it. No
    application data is sent on this connection.

    Args:
        host: Node hostname or IP.
        port: API port.
        connect_timeout: Seconds for connect plus handshake.

    Returns:
        The leaf certificate in DER form.

    Raises:
        TargetUnavailable: If the node cannot be reached or the handshake fails.
    """
    probe = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    probe.minimum_version = ssl.TLSVersion.TLSv1_2
    # Unverified on purpose: identity is established by the fingerprint compare
    # in pinned_context(), and nothing is sent before that compare passes.
    probe.check_hostname = False
    probe.verify_mode = ssl.CERT_NONE
    try:
        async with asyncio.timeout(connect_timeout):
            _, writer = await asyncio.open_connection(host, port, ssl=probe)
    except (OSError, TimeoutError) as exc:
        raise TargetUnavailable(
            "could not reach the Proxmox node to check its certificate", target=host
        ) from exc
    try:
        ssl_object = writer.get_extra_info("ssl_object")
        der = ssl_object.getpeercert(binary_form=True) if ssl_object is not None else None
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
    if not der:
        raise TargetUnavailable("the Proxmox node presented no certificate", target=host)
    return der


def pinned_context(pin: PinnedCertificate, der: bytes, *, host: str) -> ssl.SSLContext:
    """Build the API context that trusts only ``der``, after checking it against ``pin``.

    Args:
        pin: The configured fingerprint.
        der: The certificate the probe received.
        host: Node, for error context.

    Returns:
        A verifying context whose sole trust anchor is ``der``.

    Raises:
        TlsVerificationFailed: If ``der`` does not match the pin.
    """
    if not hmac.compare_digest(hashlib.sha256(der).digest(), pin.digest):
        raise TlsVerificationFailed(
            "the Proxmox node's certificate does not match the pinned fingerprint", target=host
        )
    context = _base_context(cadata=der)
    # The pin binds the exact certificate, so the hostname adds nothing; nodes
    # are often addressed by an IP their certificate does not list.
    context.check_hostname = False
    context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    # Strict RFC 5280 profile checks reject some self-generated certificates;
    # the byte-exact pin already identifies this one. Whether PVE's own
    # certificates pass the strict profile is (unverified).
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


async def build_ssl_context(
    trust: TlsTrust, *, host: str, port: int, connect_timeout: float
) -> ssl.SSLContext:
    """Return the verifying SSL context for one Proxmox endpoint.

    Args:
        trust: How the endpoint's certificate is trusted.
        host: Node hostname or IP.
        port: API port.
        connect_timeout: Seconds allowed for the pin probe.

    Returns:
        A context with ``verify_mode == CERT_REQUIRED`` in every case.

    Raises:
        InvalidInput: If the CA bundle cannot be loaded.
        TlsVerificationFailed: If a pinned certificate does not match.
        TargetUnavailable: If the pin probe cannot reach the node.
    """
    match trust:
        case SystemTrust():
            return _base_context()
        case CaBundle(path=path):
            try:
                return _base_context(cafile=str(path))
            except (OSError, ssl.SSLError) as exc:
                raise InvalidInput("the Proxmox CA bundle could not be loaded") from exc
        case PinnedCertificate():
            der = await fetch_peer_certificate(host, port, connect_timeout=connect_timeout)
            return pinned_context(trust, der, host=host)
