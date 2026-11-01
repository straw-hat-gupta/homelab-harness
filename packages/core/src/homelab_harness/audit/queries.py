"""Read-only audit queries."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from homelab_harness.audit.models import AuditEntry, AuditEvent
from homelab_harness_sdk.errors import InvalidInput

RECENT_MAX = 500


async def recent_events(
    session: AsyncSession, *, limit: int = 50, plan_id: str | None = None
) -> list[AuditEntry]:
    """Return the newest events first.

    Args:
        session: An open session.
        limit: How many events to return, 1 to 500.
        plan_id: Only events for this plan, when given.

    Returns:
        Events ordered by ``seq`` descending.

    Raises:
        InvalidInput: If ``limit`` is out of range.
    """
    if not 1 <= limit <= RECENT_MAX:
        raise InvalidInput(f"limit must be between 1 and {RECENT_MAX}")
    query = select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(limit)
    if plan_id is not None:
        query = query.where(AuditEvent.plan_id == plan_id)
    rows = await session.scalars(query)
    return [row.to_entry() for row in rows]
