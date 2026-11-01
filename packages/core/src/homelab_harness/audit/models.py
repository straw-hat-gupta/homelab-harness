"""The ``audit_events`` table.

Append-only: the initial migration installs triggers that reject UPDATE, DELETE
and TRUNCATE. In a hardened deployment the app's database role should also lack
UPDATE, DELETE and TRUNCATE grants on this table, so that a bug and a stolen
connection both hit two walls; the trigger alone does not stop a superuser.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from homelab_harness.audit.validation import ACTOR_MAX, KIND_MAX, REF_MAX
from homelab_harness.db.base import Base


class AuditEvent(Base):
    """One audit row.

    ``seq`` is a database-assigned identity (``GENERATED ALWAYS``, so a caller
    cannot choose it) with a unique constraint (R-13). It orders events by the
    time their insert started; a rolled-back insert leaves a gap.

    ``data`` holds identifiers and counts only, never payloads, target text or
    secret values. :mod:`homelab_harness.audit.validation` bounds its shape and
    the writer redacts it before insert.
    """

    __tablename__ = "audit_events"
    # Fetch id, seq and occurred_at with RETURNING on insert.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy reads a plain dict

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    kind: Mapped[str] = mapped_column(String(KIND_MAX))
    actor: Mapped[str] = mapped_column(String(ACTOR_MAX))
    plan_id: Mapped[str | None] = mapped_column(String(REF_MAX), index=True)
    job_id: Mapped[str | None] = mapped_column(String(REF_MAX))
    target: Mapped[str | None] = mapped_column(String(REF_MAX))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    def to_entry(self) -> AuditEntry:
        """Return an immutable copy detached from the session.

        Returns:
            The row as an :class:`AuditEntry`.
        """
        return AuditEntry(
            id=self.id,
            seq=self.seq,
            occurred_at=self.occurred_at,
            kind=self.kind,
            actor=self.actor,
            plan_id=self.plan_id,
            job_id=self.job_id,
            target=self.target,
            data=dict(self.data),
        )


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """An audit event as returned by the writer and queries."""

    id: uuid.UUID
    seq: int
    occurred_at: datetime
    kind: str
    actor: str
    plan_id: str | None
    job_id: str | None
    target: str | None
    data: dict[str, Any]
