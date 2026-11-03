"""Bearer authentication for ``/mcp``: OAuth access tokens, and legacy client tokens.

The MCP SDK's resource-server pieces do the HTTP side: a missing or rejected
token gets ``401`` with ``WWW-Authenticate: Bearer ..., resource_metadata="..."``
pointing at the protected resource metadata (RFC 9728), which is how an MCP
client discovers the authorization server. This module supplies the verifier.

Two kinds of token are accepted:

* **OAuth access tokens** (``hhat_...``) from the embedded authorization server
  (ADR-0007). The token must be live, its grant unrevoked, and its audience
  exactly this harness's ``/mcp`` (RFC 8707); anything else is a 401.
* **Legacy client tokens** (``hhmcp_...``) from ``homelab-harness-token``, only
  while ``HH_MCP_LEGACY_TOKENS`` is true. They are long-lived and tailnet-only;
  the plan is to default the setting to false once the OAuth clients are
  verified live, and then to remove them.
"""

from __future__ import annotations

from collections.abc import Callable

import structlog
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware, get_access_token
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import AccessToken, TokenVerifier
from pydantic import AnyHttpUrl
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.types import ASGIApp

from homelab_harness.auth.provider import (
    ACCESS_PREFIX,
    HarnessAccessToken,
    HarnessOAuthProvider,
    same_resource,
)
from homelab_harness.mcp.clients import TOKEN_PREFIX, client_for_token

log = structlog.get_logger(__name__)

# AccessToken requires a token string; the raw token is not kept in memory after
# verification, since nothing downstream needs it.
_TOKEN_PLACEHOLDER = "[client-token]"  # noqa: S105 - a label, not a credential

type SessionsProvider = Callable[[], async_sessionmaker[AsyncSession] | None]
type OAuthProvider = Callable[[], HarnessOAuthProvider | None]


class HarnessTokenVerifier(TokenVerifier):
    """Checks a bearer token: an OAuth access token, or a legacy client token if enabled."""

    def __init__(
        self,
        *,
        sessions: SessionsProvider,
        oauth: OAuthProvider,
        resource: str | None,
        legacy_tokens: bool,
    ) -> None:
        """Create the verifier.

        Args:
            sessions: Returns the session factory, or ``None`` when no database
                is configured (then every token is refused).
            oauth: Returns the authorization server's provider, or ``None``
                while OAuth is off or not started.
            resource: This harness's canonical ``/mcp`` URI, the only audience
                accepted; ``None`` when OAuth is off.
            legacy_tokens: Whether ``homelab-harness-token`` tokens are accepted.
        """
        self._sessions = sessions
        self._oauth = oauth
        self._resource = resource
        self._legacy = legacy_tokens

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return the principal for a valid token, else ``None`` (401)."""
        try:
            if token.startswith(ACCESS_PREFIX):
                return await self._oauth_token(token)
            if token.startswith(TOKEN_PREFIX):
                if not self._legacy:
                    log.info("mcp_auth_rejected", reason="legacy tokens are disabled")
                    return None
                return await self._legacy_token(token)
        except Exception as exc:  # a database outage must not become a 500 or a leak
            log.warning("mcp_auth_lookup_failed", error_type=type(exc).__name__)
            return None
        log.info("mcp_auth_rejected", reason="unknown token format")
        return None

    async def _oauth_token(self, token: str) -> AccessToken | None:
        provider = self._oauth()
        if provider is None or self._resource is None:
            log.info("mcp_auth_rejected", reason="oauth is not configured")
            return None
        principal = await provider.load_access_token(token)
        if principal is None:
            log.info("mcp_auth_rejected", reason="unknown, expired or revoked access token")
            return None
        if not same_resource(principal.resource or "", self._resource):
            log.warning("mcp_auth_rejected", reason="token audience is not this server")
            return None
        return principal

    async def _legacy_token(self, token: str) -> AccessToken | None:
        sessions = self._sessions()
        if sessions is None:
            log.warning("mcp_auth_unavailable", reason="no database configured")
            return None
        async with sessions() as session:
            client_id = await client_for_token(session, token)
        if client_id is None:
            log.info("mcp_auth_rejected", reason="unknown or revoked client token")
            return None
        return AccessToken(token=_TOKEN_PLACEHOLDER, client_id=client_id, scopes=[])


def require_bearer(
    app: ASGIApp, verifier: TokenVerifier, *, resource_metadata_url: str | None
) -> ASGIApp:
    """Wrap an ASGI app so only requests with a valid bearer token reach it.

    Args:
        app: The MCP transport app.
        verifier: Token verifier.
        resource_metadata_url: Protected resource metadata URL for the
            ``WWW-Authenticate`` challenge, or ``None`` when OAuth is off.

    Returns:
        The wrapped app; unauthenticated requests get 401 and ``WWW-Authenticate``.
    """
    metadata = AnyHttpUrl(resource_metadata_url) if resource_metadata_url else None
    return AuthenticationMiddleware(
        AuthContextMiddleware(
            RequireAuthMiddleware(app, required_scopes=[], resource_metadata_url=metadata)
        ),
        backend=BearerAuthBackend(verifier),
    )


def current_client_id() -> str:
    """The audit label of the authenticated client being served.

    OAuth clients are labelled from their client id (``cimd:<host>:<path>`` or
    ``dcr:<id>``); legacy tokens by the name they were created with.

    Raises:
        RuntimeError: If called outside an authenticated request (a wiring bug).
    """
    token = get_access_token()
    if token is None:
        raise RuntimeError("no authenticated MCP client in this context")
    if isinstance(token, HarnessAccessToken):
        return token.audit_id
    return token.client_id
