"""Create the mcp_clients table (interim bearer tokens for MCP clients).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-01

Stores one row per client: its id, the SHA-256 of its current token, and when
it was created or revoked. Downgrading drops every registration, so every
client needs a new token afterwards.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_clients",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcp_clients")),
        sa.UniqueConstraint("client_id", name=op.f("uq_mcp_clients_client_id")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_mcp_clients_token_hash")),
    )


def downgrade() -> None:
    op.drop_table("mcp_clients")
