"""Rules for OAuth clients: redirect URIs, client ids and audit labels (pure logic).

* Redirect URIs must be HTTPS, or plain HTTP to a loopback host (MCP
  authorization spec, "Communication Security"). No fragments, no credentials.
* A requested redirect URI must match a registered one exactly, except that a
  loopback URI may use any port (RFC 8252 §7.3, OAuth 2.1 §8.4.2): native
  clients such as Claude Code and Codex listen on an ephemeral port.
* The audit label of a client is derived from its id, so it can be written as
  ``client:<label>`` in the audit log without carrying ``/`` or ``?``.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull
from pydantic import AnyUrl

from homelab_harness.auth.models import AUDIT_ID_MAX

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
MAX_REDIRECT_URIS = 10
REDIRECT_URI_MAX = 2000

_LABEL_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def check_redirect_uri(uri: str) -> str | None:
    """Return why a redirect URI is unacceptable for registration, or ``None`` if it is fine."""
    if len(uri) > REDIRECT_URI_MAX:
        return "redirect URI is too long"
    parts = urlsplit(uri)
    if parts.fragment or "#" in uri:
        return "redirect URI must not have a fragment"
    if parts.username or parts.password:
        return "redirect URI must not contain credentials"
    host = (parts.hostname or "").lower()
    if not host:
        return "redirect URI must be absolute"
    if parts.scheme == "https":
        return None
    if parts.scheme == "http" and host in LOOPBACK_HOSTS:
        return None
    return "redirect URI must use https, or http to localhost"


def is_loopback_redirect(uri: str) -> bool:
    """Whether a redirect URI points at the owner's own machine."""
    parts = urlsplit(uri)
    return parts.scheme == "http" and (parts.hostname or "").lower() in LOOPBACK_HOSTS


def redirect_matches(requested: str, registered: str) -> bool:
    """Exact match, or the same loopback URI on another port."""
    if requested == registered:
        return True
    if not (is_loopback_redirect(requested) and is_loopback_redirect(registered)):
        return False
    a, b = urlsplit(requested), urlsplit(registered)
    return (
        a.scheme == b.scheme
        and (a.hostname or "").lower() == (b.hostname or "").lower()
        and a.path == b.path
        and a.query == b.query
    )


def redirect_host(uri: str) -> str:
    """The host part of a redirect URI, as shown on the consent screen."""
    return (urlsplit(uri).hostname or "").lower()


class HarnessClient(OAuthClientInformationFull):
    """Client information with the harness's redirect-URI matching.

    The SDK compares parsed URLs for equality, which normalizes them and has no
    loopback port rule. This compares the strings, as RFC 6749 §3.1.2.3 asks.
    """

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        """Return the redirect URI to use for this request.

        Raises:
            InvalidRedirectUriError: If it is not registered for this client.
        """
        registered = [str(u) for u in self.redirect_uris or []]
        if redirect_uri is None:
            if len(registered) == 1:
                return AnyUrl(registered[0])
            raise InvalidRedirectUriError(
                "redirect_uri must be specified unless the client has exactly one registered URI"
            )
        requested = str(redirect_uri)
        if any(redirect_matches(requested, r) for r in registered):
            return redirect_uri
        raise InvalidRedirectUriError("redirect_uri is not registered for this client")


def cimd_audit_id(client_id: str) -> str:
    """Audit label for a metadata-document client: ``cimd:<host>:<path segments>``.

    Long ids are cut and get a short hash of the full URL, so labels stay unique.
    """
    parts = urlsplit(client_id)
    host = (parts.hostname or "").lower()
    if parts.port is not None:
        host += f".{parts.port}"
    segments = [s for s in parts.path.split("/") if s]
    if parts.query:
        segments.append(parts.query)
    label = ":".join([_LABEL_UNSAFE.sub("-", host), *(_LABEL_UNSAFE.sub("-", s) for s in segments)])
    label = "cimd:" + label.strip("-:")
    if len(label) > AUDIT_ID_MAX - 10:
        digest = hashlib.sha256(client_id.encode()).hexdigest()[:8]
        label = label[: AUDIT_ID_MAX - 10] + ":" + digest
    return label


def clean_client_name(name: str, *, fallback: str) -> str:
    """A client's self-declared name, reduced to one short printable line."""
    printable = "".join(c for c in name if c.isprintable()).strip()
    return printable[:100] or fallback
