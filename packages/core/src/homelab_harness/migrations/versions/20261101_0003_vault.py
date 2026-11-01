"""Create the vault tables: secrets (plain metadata) and secret_versions (sealed values).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-01

``secret_versions`` holds the ciphertext and the wrapped data key of every
version; deleting a secret cascades to its versions, which is the crypto-shred.
Downgrading drops both tables: every stored secret is lost, and the KEK cannot
bring them back.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = (
    "'ssh_key', 'password', 'api_token', 'proxmox_token', "
    "'cloudflare_token', 'github_token', 'file', 'kv'"
)


def upgrade() -> None:
    op.create_table(
        "secrets",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String(length=64)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=200), server_default="local", nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotate_every", sa.Interval(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(f"kind IN ({_KINDS})", name=op.f("ck_secrets_kind")),
        sa.CheckConstraint("current_version >= 1", name=op.f("ck_secrets_current_version")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_secrets")),
        sa.UniqueConstraint("name", name=op.f("uq_secrets_name")),
    )
    op.create_table(
        "secret_versions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("secret_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("dek_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("kek_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_secret_versions_version")),
        sa.ForeignKeyConstraint(
            ["secret_id"],
            ["secrets.id"],
            name=op.f("fk_secret_versions_secret_id_secrets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_secret_versions")),
        sa.UniqueConstraint(
            "secret_id", "version", name=op.f("uq_secret_versions_secret_id_version")
        ),
    )
    op.create_index(op.f("ix_secret_versions_kek_id"), "secret_versions", ["kek_id"], unique=False)


def downgrade() -> None:
    op.drop_table("secret_versions")
    op.drop_table("secrets")
