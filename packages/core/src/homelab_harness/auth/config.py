"""The URLs and limits the owner login and the authorization server run with (pure logic).

Everything is derived from ``HH_PUBLIC_URL``, so the OAuth issuer, the passkey
relying party, the MCP resource identifier and the cookie flags can never
disagree with one another.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from pydantic import HttpUrl

from homelab_harness.settings import Settings

MCP_RESOURCE_PATH = "/mcp"
SCOPE = "mcp"
"""The one scope: use of the MCP tools. Every granted token carries it."""

AUTHORIZE_PATH = "/oauth/authorize"
TOKEN_PATH = "/oauth/token"  # noqa: S105 - a path, not a credential
REGISTER_PATH = "/oauth/register"
REVOKE_PATH = "/oauth/revoke"
CONSENT_PATH = "/oauth/consent"
AS_METADATA_PATH = "/.well-known/oauth-authorization-server"
PRM_ROOT_PATH = "/.well-known/oauth-protected-resource"
PRM_PATH = PRM_ROOT_PATH + MCP_RESOURCE_PATH
LOGIN_PATH = "/owner/login"
ENROLL_PATH = "/owner/enroll"

PENDING_TTL = timedelta(minutes=10)
CODE_TTL = timedelta(minutes=2)
CHALLENGE_TTL = timedelta(minutes=5)
ENROLLMENT_TTL = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class AuthConfig:
    """Derived auth configuration.

    Attributes:
        origin: Scheme, host and port, without a trailing slash. Also the issuer.
        rp_id: WebAuthn relying party id (the host name).
        resource: Canonical URI of the MCP server (RFC 8707), ``<origin>/mcp``.
        secure_cookies: Whether cookies get ``Secure`` (and the ``__Host-`` prefix).
        access_token_ttl: Lifetime of an access token.
        refresh_token_ttl: Lifetime of a refresh token.
        session_idle: Owner session idle timeout.
        session_max: Owner session absolute lifetime.
        dcr_enabled: Whether ``/oauth/register`` is served.
        legacy_tokens: Whether ``/mcp`` accepts interim bearer tokens too.
    """

    origin: str
    rp_id: str
    resource: str
    secure_cookies: bool
    access_token_ttl: timedelta
    refresh_token_ttl: timedelta
    session_idle: timedelta
    session_max: timedelta
    dcr_enabled: bool
    legacy_tokens: bool

    @property
    def issuer(self) -> str:
        """The authorization server's issuer identifier (RFC 8414): the origin."""
        return self.origin

    @property
    def session_cookie(self) -> str:
        """Cookie name; ``__Host-`` pins it to this origin when it can be ``Secure``."""
        return "__Host-hh_owner" if self.secure_cookies else "hh_owner"

    @property
    def resource_metadata_url(self) -> str:
        """Where the protected resource metadata for ``/mcp`` lives (RFC 9728 §3.1)."""
        return self.origin + PRM_PATH

    def url(self, path: str) -> str:
        """Absolute URL of a path on this harness."""
        return self.origin + path


def origin_of(url: HttpUrl) -> str:
    """Return ``scheme://host[:port]`` with the default port left out."""
    default = {"https": 443, "http": 80}.get(url.scheme)
    port = f":{url.port}" if url.port is not None and url.port != default else ""
    return f"{url.scheme}://{url.host}{port}"


def auth_config(settings: Settings) -> AuthConfig | None:
    """Derive the auth configuration, or ``None`` when ``HH_PUBLIC_URL`` is unset.

    Args:
        settings: Process settings; ``public_url`` was validated when they loaded.

    Returns:
        The configuration, or ``None`` (OAuth and owner login off).
    """
    if settings.public_url is None:
        return None
    url = settings.public_url
    origin = origin_of(url)
    return AuthConfig(
        origin=origin,
        rp_id=(url.host or "").strip("[]"),
        resource=origin + MCP_RESOURCE_PATH,
        secure_cookies=url.scheme == "https",
        access_token_ttl=timedelta(seconds=settings.oauth_access_token_seconds),
        refresh_token_ttl=timedelta(seconds=settings.oauth_refresh_token_seconds),
        session_idle=timedelta(seconds=settings.owner_session_idle_seconds),
        session_max=timedelta(seconds=settings.owner_session_max_seconds),
        dcr_enabled=settings.oauth_dcr_enabled,
        legacy_tokens=settings.mcp_legacy_tokens,
    )
