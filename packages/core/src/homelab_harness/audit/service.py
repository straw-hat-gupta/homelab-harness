"""Writing audit events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from homelab_harness.audit.models import AuditEntry, AuditEvent
from homelab_harness.audit.validation import validate_audit_input
from homelab_harness.redaction import Redactor, redactor


class AuditWriter:
    """Appends validated, redacted events to ``audit_events``."""

    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], *, scrubber: Redactor = redactor
    ) -> None:
        """Create a writer.

        Args:
            sessions: Session factory for standalone writes.
            scrubber: Redactor applied to ``data``; the process-wide one by default.
        """
        self._sessions = sessions
        self._scrubber = scrubber

    async def record(
        self,
        *,
        kind: str,
        actor: str,
        plan_id: str | None = None,
        job_id: str | None = None,
        target: str | None = None,
        data: Mapping[str, object] | None = None,
        session: AsyncSession | None = None,
    ) -> AuditEntry:
        """Validate, redact and insert one event.

        Args:
            kind: Dotted event name, for example ``plan.created``.
            actor: ``owner``, ``system``, or ``client:<client_id>``.
            plan_id: Plan the event concerns, if any.
            job_id: Job the event concerns, if any.
            target: Target reference, if any.
            data: Identifiers and counts only (see
                :func:`~homelab_harness.audit.validation.validate_audit_input`).
            session: A caller's open session. When given, the event joins the
                caller's transaction, so it commits or rolls back with the state
                change it describes. Otherwise the writer commits on its own.

        Returns:
            The stored event, with its database-assigned ``id``, ``seq`` and
            ``occurred_at``.

        Raises:
            InvalidInput: If the input breaks the audit rules.
        """
        valid = validate_audit_input(
            kind=kind, actor=actor, plan_id=plan_id, job_id=job_id, target=target, data=data
        )
        scrubbed: dict[str, Any] = self._scrubber.scrub(valid.data)
        row = AuditEvent(
            kind=valid.kind,
            actor=valid.actor,
            plan_id=valid.plan_id,
            job_id=valid.job_id,
            target=valid.target,
            data=scrubbed,
        )
        if session is not None:
            session.add(row)
            await session.flush()
            return row.to_entry()
        async with self._sessions.begin() as own:
            own.add(row)
            await own.flush()
            return row.to_entry()
