"""Every client that can reach the harness, for ``hh clients`` and ``homelab-harness-token``.

Two kinds live side by side: OAuth clients (metadata-document or dynamically
registered; identified by their audit label) and legacy client tokens
(identified by the name they were created with). The labels cannot collide:
OAuth labels contain ``:`` and legacy names may not.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from homelab_harness.auth.models import OAuthClient, OAuthGrant
from homelab_harness.mcp.clients import list_clients, revoke_client


@dataclass(frozen=True, slots=True)
class ClientSummary:
    """One client as shown to the owner.

    Attributes:
        id: Audit label (``client:<id>`` in the audit log); what ``revoke`` takes.
        kind: ``oauth-cimd``, ``oauth-dcr``, ``token-mcp`` or ``token-owner``.
        name: Display name (an OAuth client's self-declared name).
        created_at: When it was first seen or created.
        active: Live grants (OAuth) or 1/0 for an unrevoked token.
    """

    id: str
    kind: str
    name: str
    created_at: datetime
    active: int


async def list_all_clients(session: AsyncSession) -> list[ClientSummary]:
    """Return OAuth clients and legacy token clients, oldest first."""
    live = (
        select(OAuthGrant.client_id, func.count().label("n"))
        .where(OAuthGrant.revoked_at.is_(None))
        .group_by(OAuthGrant.client_id)
        .subquery()
    )
    rows = await session.execute(
        select(OAuthClient, func.coalesce(live.c.n, 0))
        .outerjoin(live, live.c.client_id == OAuthClient.client_id)
        .order_by(OAuthClient.created_at)
    )
    out = [
        ClientSummary(
            id=client.audit_id,
            kind=f"oauth-{client.kind}",
            name=client.client_name,
            created_at=client.created_at,
            active=int(count),
        )
        for client, count in rows
    ]
    out += [
        ClientSummary(
            id=c.client_id,
            kind=f"token-{c.role}",
            name=c.client_id,
            created_at=c.created_at,
            active=0 if c.revoked_at else 1,
        )
        for c in await list_clients(session)
    ]
    return sorted(out, key=lambda c: c.created_at)


async def revoke_any_client(session: AsyncSession, *, client_id: str, now: datetime) -> int:
    """Revoke an OAuth client's grants or a legacy client's token.

    Revoking an OAuth client ends every grant it holds at once; it can only
    regain access through a new consent by the owner.

    Args:
        session: An open session; the caller commits.
        client_id: The id ``list_all_clients`` shows.
        now: Revocation time.

    Returns:
        How many grants or tokens were revoked.

    Raises:
        NotFound: If no client has this id.
    """
    oauth = await session.scalar(select(OAuthClient).where(OAuthClient.audit_id == client_id))
    if oauth is None:
        await revoke_client(session, client_id=client_id)
        return 1
    result = await session.execute(
        update(OAuthGrant)
        .where(OAuthGrant.client_id == oauth.client_id, OAuthGrant.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason="owner_revoked")
    )
    return int(getattr(result, "rowcount", 0) or 0)
