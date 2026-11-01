"""Bearer-token authentication for ``/mcp`` (interim, until the OAuth server lands).

The MCP SDK's resource-server pieces do the HTTP side: a missing or rejected
token gets ``401`` with ``WWW-Authenticate: Bearer``. This module supplies the
verifier they call, backed by the ``mcp_clients`` table. The OAuth PR
(ADR-0007) replaces the verifier and keeps the rest.

Tailnet only: these are long-lived owner tokens with no expiry. Do not expose
``/mcp`` publicly with them.
"""

from __future__ import annotations

from collections.abc import Callable

import structlog
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware, get_access_token
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import AccessToken, TokenVerifier
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.types import ASGIApp

from homelab_harness.mcp.clients import client_for_token

log = structlog.get_logger(__name__)

# AccessToken requires a token string; the raw token is not kept in memory after
# verification, since nothing downstream needs it.
_TOKEN_PLACEHOLDER = "[client-token]"  # noqa: S105 - a label, not a credential

type SessionsProvider = Callable[[], async_sessionmaker[AsyncSession] | None]


class ClientTokenVerifier(TokenVerifier):
    """Checks a bearer token against the registered clients."""

    def __init__(self, sessions: SessionsProvider) -> None:
        """Create the verifier.

        Args:
            sessions: Returns the session factory, or ``None`` when no database
                is configured (then every token is refused).
        """
        self._sessions = sessions

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return the principal for a valid, unrevoked token, else ``None`` (401)."""
        sessions = self._sessions()
        if sessions is None:
            log.warning("mcp_auth_unavailable", reason="no database configured")
            return None
        try:
            async with sessions() as session:
                client_id = await client_for_token(session, token)
        except Exception as exc:  # a database outage must not become a 500 or a leak
            log.warning("mcp_auth_lookup_failed", error_type=type(exc).__name__)
            return None
        if client_id is None:
            log.info("mcp_auth_rejected")
            return None
        return AccessToken(token=_TOKEN_PLACEHOLDER, client_id=client_id, scopes=[])


def require_bearer(app: ASGIApp, verifier: TokenVerifier) -> ASGIApp:
    """Wrap an ASGI app so only requests with a valid bearer token reach it.

    Args:
        app: The MCP transport app.
        verifier: Token verifier.

    Returns:
        The wrapped app; unauthenticated requests get 401 and ``WWW-Authenticate``.
    """
    return AuthenticationMiddleware(
        AuthContextMiddleware(RequireAuthMiddleware(app, required_scopes=[])),
        backend=BearerAuthBackend(verifier),
    )


def current_client_id() -> str:
    """The client id of the authenticated request being served.

    Raises:
        RuntimeError: If called outside an authenticated request (a wiring bug).
    """
    token = get_access_token()
    if token is None:
        raise RuntimeError("no authenticated MCP client in this context")
    return token.client_id
