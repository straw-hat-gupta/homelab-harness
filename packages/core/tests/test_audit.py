import uuid
from datetime import UTC

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from homelab_harness.audit.queries import recent_events
from homelab_harness.audit.service import AuditWriter
from homelab_harness.redaction import MASK, redactor
from homelab_harness_sdk.errors import InvalidInput

CANARY = "hh-canary-audit-9f3c2e71"


@pytest.fixture
def writer(sessions):
    return AuditWriter(sessions)


@pytest.fixture
def plan_id():
    # Each test gets its own plan so tests sharing the database stay independent.
    return f"p_{uuid.uuid4().hex[:10]}"


async def test_record_returns_database_assigned_fields(writer, plan_id):
    first = await writer.record(kind="plan.created", actor="client:claude-code", plan_id=plan_id)
    second = await writer.record(
        kind="plan.approved", actor="owner", plan_id=plan_id, data={"tier": 3}
    )
    assert first.seq < second.seq
    assert first.id != second.id
    assert first.occurred_at.tzinfo is not None
    assert first.occurred_at.utcoffset() == UTC.utcoffset(None)
    assert first.data == {}
    assert second.data == {"tier": 3}


async def test_recent_events_newest_first_and_filtered_by_plan(writer, sessions, plan_id):
    for kind in ("plan.created", "plan.approved", "job.started"):
        await writer.record(kind=kind, actor="system", plan_id=plan_id)
    await writer.record(kind="plan.created", actor="system", plan_id=f"{plan_id}_other")
    async with sessions() as session:
        events = await recent_events(session, plan_id=plan_id)
        latest_two = await recent_events(session, plan_id=plan_id, limit=2)
    assert [e.kind for e in events] == ["job.started", "plan.approved", "plan.created"]
    assert [e.kind for e in latest_two] == ["job.started", "plan.approved"]


@pytest.mark.parametrize("limit", [0, 501])
async def test_recent_events_rejects_out_of_range_limits(sessions, limit):
    async with sessions() as session:
        with pytest.raises(InvalidInput):
            await recent_events(session, limit=limit)


async def test_event_joins_the_callers_transaction(writer, sessions, plan_id):
    async with sessions() as session:
        await writer.record(kind="plan.created", actor="owner", plan_id=plan_id, session=session)
        await session.rollback()
    async with sessions() as session:
        assert await recent_events(session, plan_id=plan_id) == []


async def test_invalid_input_is_rejected_before_insert(writer):
    with pytest.raises(InvalidInput):
        await writer.record(kind="Not A Kind", actor="owner")


async def test_canary_secret_never_reaches_the_table(writer, engine, plan_id):
    # R-16: values registered with the redactor are masked in audit data, and
    # sensitive keys are masked whatever they hold.
    redactor.register(CANARY)
    try:
        entry = await writer.record(
            kind="secret.used",
            actor="system",
            plan_id=plan_id,
            data={"upstream": f"https://api.example/?k={CANARY}", "token": "short-but-sensitive"},
        )
    finally:
        redactor.clear()
    assert entry.data == {"upstream": f"https://api.example/?k={MASK}", "token": MASK}
    async with engine.connect() as conn:
        raw = await conn.scalar(
            text("SELECT data::text FROM audit_events WHERE plan_id = :p"), {"p": plan_id}
        )
    assert CANARY not in raw
    assert "short-but-sensitive" not in raw


async def test_seq_is_unique_and_cannot_be_chosen_by_the_caller(writer, engine, plan_id):
    # R-13: event order is enforced by the database, not by the writer.
    entry = await writer.record(kind="plan.created", actor="system", plan_id=plan_id)
    insert = "INSERT INTO audit_events (seq, kind, actor) VALUES (:seq, 'x.y', 'system')"
    async with engine.connect() as conn:
        with pytest.raises(DBAPIError, match="GENERATED ALWAYS"):
            await conn.execute(text(insert), {"seq": entry.seq + 10_000})
    async with engine.connect() as conn:
        overriding = insert.replace("VALUES", "OVERRIDING SYSTEM VALUE VALUES")
        with pytest.raises(IntegrityError, match="uq_audit_events_seq"):
            await conn.execute(text(overriding), {"seq": entry.seq})


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET kind = 'tampered.kind' WHERE plan_id = :p",
        "DELETE FROM audit_events WHERE plan_id = :p",
        "TRUNCATE audit_events",
    ],
)
async def test_audit_rows_cannot_be_changed_or_removed(writer, engine, plan_id, statement):
    await writer.record(kind="plan.created", actor="system", plan_id=plan_id)
    async with engine.connect() as conn:
        with pytest.raises(DBAPIError, match="append-only"):
            await conn.execute(text(statement), {"p": plan_id})
    async with engine.connect() as conn:
        kinds = (
            await conn.scalars(
                text("SELECT kind FROM audit_events WHERE plan_id = :p"), {"p": plan_id}
            )
        ).all()
    assert kinds == ["plan.created"]
