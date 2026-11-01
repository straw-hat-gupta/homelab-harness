"""Give every client registration a role: mcp (AI clients) or owner (the hh CLI).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-01

Existing registrations become ``mcp``, which is what they were created for.
Downgrading drops the column, which turns owner tokens into MCP tokens, so
revoke them first.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_clients",
        sa.Column("role", sa.String(length=16), server_default="mcp", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_mcp_clients_role"), "mcp_clients", "role IN ('mcp', 'owner')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_mcp_clients_role"), "mcp_clients", type_="check")
    op.drop_column("mcp_clients", "role")
