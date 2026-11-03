"""Client ID Metadata Documents: validating the URL, fetching it safely, checking the document.

An MCP client may use an HTTPS URL as its ``client_id``; the authorization
server fetches the JSON document at that URL to learn the client's name and
redirect URIs (draft-ietf-oauth-client-id-metadata-document-00, adopted by the
MCP 2026-07-28 authorization spec). Anyone can make the harness fetch a URL
this way, so the fetch is a server-side request forgery surface (draft §6.5):

* ``https`` only, a path is required, no fragment, credentials or dot segments;
* the host is resolved once, every resolved address must be public (no
  loopback, private, link-local, CGNAT/tailnet, multicast or reserved ranges),
  and the connection goes to that checked address with the original name used
  for TLS (SNI and certificate check), so DNS rebinding cannot swap it;
* no redirects, a 5 s total timeout, at most 5 KiB (draft §6.6), JSON only;
* the document's ``client_id`` must equal the URL exactly (draft §4.1), and it
  may not declare a shared secret or a secret-based auth method (draft §4.5).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
import structlog
from pydantic import AnyUrl, ValidationError

from homelab_harness.auth.client_rules import (
    MAX_REDIRECT_URIS,
    check_redirect_uri,
    clean_client_name,
)
from homelab_harness.auth.models import CLIENT_ID_MAX

log = structlog.get_logger(__name__)

MAX_DOCUMENT_BYTES = 5 * 1024
FETCH_TIMEOUT_SECONDS = 5.0
MIN_CACHE = timedelta(minutes=5)
MAX_CACHE = timedelta(hours=24)
DEFAULT_CACHE = timedelta(hours=1)

type Resolver = Callable[[str, int], Awaitable[Sequence[str]]]


class CimdError(Exception):
    """The client id or its document is unacceptable; the message is safe to show."""


@dataclass(frozen=True, slots=True)
class ClientDocument:
    """What the harness keeps from a validated metadata document."""

    client_id: str
    client_name: str
    redirect_uris: list[str]
    cache_for: timedelta


def looks_like_cimd(client_id: str) -> bool:
    """Whether a ``client_id`` is URL-formatted and so names a metadata document."""
    return client_id.startswith("https://")


def check_client_id_url(client_id: str) -> tuple[str, int]:
    """Validate a metadata-document client id and return ``(host, port)``.

    Raises:
        CimdError: If the URL breaks a rule of draft §3 or the harness's limits.
    """
    if len(client_id) > CLIENT_ID_MAX:
        raise CimdError("client_id URL is too long")
    try:
        parts = urlsplit(client_id)
        port = parts.port or 443
    except ValueError:
        raise CimdError("client_id is not a valid URL") from None
    if parts.scheme != "https":
        raise CimdError("client_id URL must use https")
    if not parts.hostname:
        raise CimdError("client_id URL has no host")
    if parts.username or parts.password:
        raise CimdError("client_id URL must not contain credentials")
    if parts.fragment or "#" in client_id:
        raise CimdError("client_id URL must not have a fragment")
    segments = parts.path.split("/")
    if parts.path in ("", "/") or any(s in (".", "..") for s in segments):
        raise CimdError("client_id URL must have a path without dot segments")
    return parts.hostname.lower(), port


def is_public_address(address: str) -> bool:
    """Whether an IP address is globally routable (not loopback, private, tailnet …)."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # is_global excludes RFC 1918, loopback, link-local, 100.64/10 (Tailscale),
    # ULA, documentation and reserved ranges; multicast is excluded separately.
    return ip.is_global and not ip.is_multicast


async def system_resolver(host: str, port: int) -> Sequence[str]:
    """Resolve a host with the system resolver, returning every address."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def parse_document(client_id: str, body: bytes, *, cache_control: str | None) -> ClientDocument:
    """Validate a fetched document against its URL.

    Raises:
        CimdError: If it is not a JSON object with the required, consistent fields.
    """
    try:
        raw: object = json.loads(body)
    except ValueError:
        raise CimdError("client metadata document is not valid JSON") from None
    if not isinstance(raw, dict):
        raise CimdError("client metadata document must be a JSON object")
    doc = cast(dict[str, Any], raw)
    if doc.get("client_id") != client_id:
        raise CimdError("client metadata document's client_id does not match its URL")
    for forbidden in ("client_secret", "client_secret_expires_at"):
        if forbidden in doc:
            raise CimdError(f"client metadata document must not contain {forbidden}")
    method = doc.get("token_endpoint_auth_method", "none")
    if method != "none":
        raise CimdError("only public clients (token_endpoint_auth_method 'none') are supported")
    grant_types = doc.get("grant_types", ["authorization_code"])
    if not isinstance(grant_types, list) or "authorization_code" not in grant_types:
        raise CimdError("client metadata document must allow the authorization_code grant")
    response_types = doc.get("response_types", ["code"])
    if not isinstance(response_types, list) or "code" not in response_types:
        raise CimdError("client metadata document must allow the code response type")
    name = doc.get("client_name")
    if not isinstance(name, str) or not name.strip():
        raise CimdError("client metadata document must have a client_name")
    return ClientDocument(
        client_id=client_id,
        client_name=clean_client_name(name, fallback=client_id),
        redirect_uris=_redirect_uris(doc.get("redirect_uris")),
        cache_for=cache_lifetime(cache_control),
    )


def _redirect_uris(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise CimdError("client metadata document must list redirect_uris")
    items = cast(list[object], value)
    if len(items) > MAX_REDIRECT_URIS:
        raise CimdError(
            f"client metadata document lists more than {MAX_REDIRECT_URIS} redirect URIs"
        )
    uris: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise CimdError("redirect_uris must be strings")
        problem = check_redirect_uri(item)
        if problem is not None:
            raise CimdError(problem)
        try:
            uris.append(str(AnyUrl(item)))
        except ValidationError:
            raise CimdError("redirect URI is not a valid URL") from None
    return uris


def cache_lifetime(cache_control: str | None) -> timedelta:
    """How long to keep a document: its ``max-age``, clamped to 5 min to 24 h (draft §4.4)."""
    if not cache_control:
        return DEFAULT_CACHE
    directives = [d.strip().lower() for d in cache_control.split(",")]
    if "no-store" in directives or "no-cache" in directives:
        return MIN_CACHE
    for directive in directives:
        name, _, value = directive.partition("=")
        if name == "max-age" and value.isdigit():
            return min(MAX_CACHE, max(MIN_CACHE, timedelta(seconds=int(value))))
    return DEFAULT_CACHE


class CimdFetcher:
    """Fetches metadata documents under the SSRF rules in the module docstring."""

    def __init__(
        self,
        *,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = FETCH_TIMEOUT_SECONDS,
    ) -> None:
        """Create a fetcher.

        Args:
            resolver: Host resolver; injectable so tests need no DNS.
            transport: httpx transport; tests pass a mock.
            timeout_seconds: Limit on the whole fetch, connect to last byte.
        """
        self._resolver = resolver
        self._transport = transport
        self._timeout = timeout_seconds

    async def fetch(self, client_id: str) -> ClientDocument:
        """Fetch and validate the document a client id names.

        Raises:
            CimdError: If the URL, the resolved address, the response or the
                document breaks a rule. The message never echoes the body.
        """
        host, port = check_client_id_url(client_id)
        try:
            async with asyncio.timeout(self._timeout):
                address = await self._public_address(host, port)
                body, cache_control = await self._get(client_id, host, address)
        except TimeoutError:
            raise CimdError("fetching the client metadata document timed out") from None
        return parse_document(client_id, body, cache_control=cache_control)

    async def _public_address(self, host: str, port: int) -> str:
        try:
            addresses = list(await self._resolver(host, port))
        except OSError:
            raise CimdError("the client_id host does not resolve") from None
        if not addresses:
            raise CimdError("the client_id host does not resolve")
        # All, not any: a name that also resolves to an internal address is refused.
        if not all(is_public_address(a) for a in addresses):
            log.warning("cimd_refused_address", host=host, reason="non-public address")
            raise CimdError("the client_id host resolves to a non-public address")
        return addresses[0]

    async def _get(self, client_id: str, host: str, address: str) -> tuple[bytes, str | None]:
        parts = urlsplit(client_id)
        ip_host = f"[{address}]" if ":" in address else address
        netloc = ip_host if parts.port is None else f"{ip_host}:{parts.port}"
        pinned = parts._replace(netloc=netloc).geturl()
        host_header = host if parts.port is None else f"{host}:{parts.port}"
        async with httpx.AsyncClient(
            transport=self._transport,
            follow_redirects=False,
            timeout=self._timeout,
            trust_env=False,  # never route through a proxy from the environment
        ) as client:
            request = client.build_request(
                "GET",
                pinned,
                headers={"Host": host_header, "Accept": "application/json"},
                # TLS server name and certificate check use the real host name.
                extensions={"sni_hostname": host},
            )
            try:
                response = await client.send(request, stream=True)
            except httpx.HTTPError as exc:
                log.info("cimd_fetch_failed", host=host, error_type=type(exc).__name__)
                raise CimdError("the client metadata document could not be fetched") from None
            try:
                if response.status_code != 200:
                    raise CimdError(
                        f"the client metadata document answered HTTP {response.status_code}"
                    )
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                if content_type != "application/json" and not content_type.endswith("+json"):
                    raise CimdError("the client metadata document is not JSON")
                declared = response.headers.get("content-length")
                if (
                    declared is not None
                    and declared.isdigit()
                    and int(declared) > MAX_DOCUMENT_BYTES
                ):
                    raise CimdError("the client metadata document is too large")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_DOCUMENT_BYTES:
                        raise CimdError("the client metadata document is too large")
                return bytes(body), response.headers.get("cache-control")
            finally:
                await response.aclose()
