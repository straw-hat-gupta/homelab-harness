"""Create the append-only audit_events table.

Revision ID: 0001
Revises:
Create Date: 2026-10-31

Triggers reject UPDATE, DELETE and TRUNCATE, so the table is append-only even
for the role that owns it. Downgrading drops the table and every event in it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REJECT_FUNCTION = """
CREATE FUNCTION audit_events_reject_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$
"""


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=160), nullable=False),
        sa.Column("plan_id", sa.String(length=200), nullable=True),
        sa.Column("job_id", sa.String(length=200), nullable=True),
        sa.Column("target", sa.String(length=200), nullable=True),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
        sa.UniqueConstraint("seq", name=op.f("uq_audit_events_seq")),
    )
    op.create_index(op.f("ix_audit_events_plan_id"), "audit_events", ["plan_id"], unique=False)
    op.execute(_REJECT_FUNCTION)
    op.execute(
        "CREATE TRIGGER audit_events_no_update_delete BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_reject_change()"
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_events_reject_change()"
    )


def downgrade() -> None:
    op.drop_table("audit_events")  # drops its triggers too
    op.execute("DROP FUNCTION audit_events_reject_change()")
