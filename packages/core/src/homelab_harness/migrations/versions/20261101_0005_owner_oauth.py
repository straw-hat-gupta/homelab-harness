"""Add the owner's identity (passkeys, recovery codes, sessions) and the OAuth server's tables.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-01

All new tables; nothing existing changes. Downgrading drops them, which ends
every owner session and OAuth grant (clients must sign in again after a
re-upgrade) and forgets the enrolled owner, who must enroll again.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.String(length=512), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("audit_id", sa.String(length=150), nullable=False),
        sa.Column("client_name", sa.String(length=100), nullable=False),
        sa.Column("redirect_uris", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("metadata_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('cimd', 'dcr')", name=op.f("ck_oauth_clients_kind")),
        sa.PrimaryKeyConstraint("client_id", name=op.f("pk_oauth_clients")),
        sa.UniqueConstraint("audit_id", name=op.f("uq_oauth_clients_audit_id")),
    )
    op.create_table(
        "owner",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("singleton", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("user_handle", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("singleton", name=op.f("ck_owner_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_owner")),
        sa.UniqueConstraint("singleton", name=op.f("uq_owner_singleton")),
    )
    op.create_table(
        "owner_enrollment_tokens",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_owner_enrollment_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_owner_enrollment_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_owner_enrollment_tokens_expires_at"),
        "owner_enrollment_tokens",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "owner_passkeys",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_owner_passkeys")),
        sa.UniqueConstraint("credential_id", name=op.f("uq_owner_passkeys_credential_id")),
    )
    op.create_table(
        "owner_recovery_codes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("lookup", sa.String(length=8), nullable=False),
        sa.Column("code_hash", sa.String(length=256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_owner_recovery_codes")),
        sa.UniqueConstraint("lookup", name=op.f("uq_owner_recovery_codes_lookup")),
    )
    op.create_table(
        "owner_sessions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "method IN ('passkey', 'recovery_code')", name=op.f("ck_owner_sessions_method")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_owner_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_owner_sessions_token_hash")),
    )
    op.create_index(
        op.f("ix_owner_sessions_expires_at"), "owner_sessions", ["expires_at"], unique=False
    )
    op.create_table(
        "webauthn_challenges",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("challenge", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('register', 'login')", name=op.f("ck_webauthn_challenges_purpose")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webauthn_challenges")),
    )
    op.create_index(
        op.f("ix_webauthn_challenges_expires_at"),
        "webauthn_challenges",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "oauth_grants",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", sa.String(length=512), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.client_id"],
            name=op.f("fk_oauth_grants_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_grants")),
    )
    op.create_index(op.f("ix_oauth_grants_client_id"), "oauth_grants", ["client_id"], unique=False)
    op.create_table(
        "oauth_pending_authorizations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", sa.String(length=512), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("redirect_uri_explicit", sa.Boolean(), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.client_id"],
            name=op.f("fk_oauth_pending_authorizations_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_pending_authorizations")),
    )
    op.create_index(
        op.f("ix_oauth_pending_authorizations_expires_at"),
        "oauth_pending_authorizations",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "oauth_authorization_codes",
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=512), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("redirect_uri_explicit", sa.Boolean(), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grant_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.client_id"],
            name=op.f("fk_oauth_authorization_codes_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["oauth_grants.id"],
            name=op.f("fk_oauth_authorization_codes_grant_id_oauth_grants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("code_hash", name=op.f("pk_oauth_authorization_codes")),
    )
    op.create_index(
        op.f("ix_oauth_authorization_codes_expires_at"),
        "oauth_authorization_codes",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "oauth_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('access', 'refresh')", name=op.f("ck_oauth_tokens_kind")),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["oauth_grants.id"],
            name=op.f("fk_oauth_tokens_grant_id_oauth_grants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_oauth_tokens")),
    )
    op.create_index(
        op.f("ix_oauth_tokens_expires_at"), "oauth_tokens", ["expires_at"], unique=False
    )
    op.create_index(op.f("ix_oauth_tokens_grant_id"), "oauth_tokens", ["grant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_oauth_tokens_grant_id"), table_name="oauth_tokens")
    op.drop_index(op.f("ix_oauth_tokens_expires_at"), table_name="oauth_tokens")
    op.drop_table("oauth_tokens")
    op.drop_index(
        op.f("ix_oauth_authorization_codes_expires_at"), table_name="oauth_authorization_codes"
    )
    op.drop_table("oauth_authorization_codes")
    op.drop_index(
        op.f("ix_oauth_pending_authorizations_expires_at"),
        table_name="oauth_pending_authorizations",
    )
    op.drop_table("oauth_pending_authorizations")
    op.drop_index(op.f("ix_oauth_grants_client_id"), table_name="oauth_grants")
    op.drop_table("oauth_grants")
    op.drop_index(op.f("ix_webauthn_challenges_expires_at"), table_name="webauthn_challenges")
    op.drop_table("webauthn_challenges")
    op.drop_index(op.f("ix_owner_sessions_expires_at"), table_name="owner_sessions")
    op.drop_table("owner_sessions")
    op.drop_table("owner_recovery_codes")
    op.drop_table("owner_passkeys")
    op.drop_index(
        op.f("ix_owner_enrollment_tokens_expires_at"), table_name="owner_enrollment_tokens"
    )
    op.drop_table("owner_enrollment_tokens")
    op.drop_table("owner")
    op.drop_table("oauth_clients")
