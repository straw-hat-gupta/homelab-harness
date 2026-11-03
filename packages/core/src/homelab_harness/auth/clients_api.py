"""The owner API for clients: ``GET /api/clients`` and ``POST /api/clients/{id}/revoke``.

Used by ``hh clients list|revoke``. Interface layer; requires an owner token.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from homelab_harness.audit.service import AuditWriter
from homelab_harness.auth.registry import list_all_clients, revoke_any_client
from homelab_harness.owner_auth import require_owner
from homelab_harness_sdk.errors import NotFound

router = APIRouter(prefix="/api", tags=["clients"], dependencies=[Depends(require_owner)])


class ClientResponse(BaseModel):
    """One client."""

    id: str
    kind: str
    name: str
    created_at: datetime
    active: int


class ClientListResponse(BaseModel):
    """Every client, oldest first."""

    clients: list[ClientResponse]


class RevokeResponse(BaseModel):
    """What a revocation ended."""

    id: str
    revoked: int


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    sessions: async_sessionmaker[AsyncSession] | None = getattr(
        request.app.state, "db_sessions", None
    )
    if sessions is None:
        raise HTTPException(503, detail="no database configured")
    return sessions


@router.get("/clients")
async def list_clients_route(request: Request) -> ClientListResponse:
    """List OAuth clients and legacy client tokens."""
    async with _sessions(request)() as session:
        rows = await list_all_clients(session)
    return ClientListResponse(
        clients=[
            ClientResponse(
                id=r.id, kind=r.kind, name=r.name, created_at=r.created_at, active=r.active
            )
            for r in rows
        ]
    )


@router.post("/clients/{client_id}/revoke")
async def revoke_client_route(client_id: str, request: Request) -> RevokeResponse:
    """Revoke every grant of an OAuth client, or a legacy client's token."""
    audit: AuditWriter = request.app.state.audit
    try:
        async with _sessions(request).begin() as session:
            count = await revoke_any_client(session, client_id=client_id, now=datetime.now(UTC))
            await audit.record(
                kind="client.revoked",
                actor="owner",
                data={"client": client_id, "revoked": count},
                session=session,
            )
    except NotFound as exc:
        raise HTTPException(404, detail=exc.safe_message) from None
    return RevokeResponse(id=client_id, revoked=count)
