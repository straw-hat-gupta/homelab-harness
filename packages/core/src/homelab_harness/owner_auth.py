"""Owner authentication for the REST API under ``/api`` (interim, until the OAuth server lands).

``hh`` sends an owner bearer token, created with
``homelab-harness-token create --client <name> --role owner``. MCP tokens are
refused here, and owner tokens are refused at ``/mcp``, so a token handed to an
AI client can never manage the vault. Tailnet only, like the MCP tokens.
"""

from __future__ import annotations

import structlog
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from homelab_harness.mcp.clients import ClientRole, client_for_token

log = structlog.get_logger(__name__)

_CHALLENGE = {"WWW-Authenticate": "Bearer"}


def _unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail="an owner token is required", headers=_CHALLENGE
    )


async def require_owner(request: Request) -> str:
    """FastAPI dependency: accept only a valid, unrevoked owner token.

    Args:
        request: The incoming request.

    Returns:
        The owner client's id.

    Raises:
        HTTPException: 401 for a missing, malformed, unknown, revoked or non-owner
            token; 503 when no database is configured or it cannot be reached.
    """
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized()
    sessions: async_sessionmaker[AsyncSession] | None = getattr(
        request.app.state, "db_sessions", None
    )
    if sessions is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="no database configured")
    try:
        async with sessions() as session:
            client_id = await client_for_token(session, token, role=ClientRole.OWNER)
    except Exception as exc:  # a database outage must not become a 500 or a leak
        log.warning("owner_auth_lookup_failed", error_type=type(exc).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="token check unavailable"
        ) from None
    if client_id is None:
        log.info("owner_auth_rejected")
        raise _unauthorized()
    return client_id
