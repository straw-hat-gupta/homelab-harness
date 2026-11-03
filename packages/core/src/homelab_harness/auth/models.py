"""Tables for the owner's identity and the embedded OAuth authorization server (ADR-0007).

Nothing here stores a usable secret. Session tokens, enrollment tokens,
authorization codes and OAuth tokens are stored as SHA-256 hashes (they are
256-bit random values, so a fast hash is enough; see
:mod:`homelab_harness.mcp.clients`). Recovery codes are shorter and printed on
paper, so they get a salted scrypt hash. Passkeys store only public keys.

The ``owner`` table holds at most one row: a unique, always-true ``singleton``
column makes a second owner a constraint violation, not just an application check.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from homelab_harness.db.base import Base

HASH_LEN = 64
CLIENT_ID_MAX = 512
AUDIT_ID_MAX = 150
CLIENT_NAME_MAX = 100


class Owner(Base):
    """The one human the harness serves. ``enrolled_at`` is set once a passkey exists."""

    __tablename__ = "owner"
    __table_args__ = (CheckConstraint("singleton", name="singleton"),)
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy reads a plain dict

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    singleton: Mapped[bool] = mapped_column(Boolean, unique=True, server_default=text("true"))
    user_handle: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OwnerPasskey(Base):
    """A WebAuthn credential registered by the owner: its id and public key only."""

    __tablename__ = "owner_passkeys"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OwnerRecoveryCode(Base):
    """One printed recovery code: a public lookup prefix and a scrypt hash of the rest."""

    __tablename__ = "owner_recovery_codes"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    lookup: Mapped[str] = mapped_column(String(8), unique=True)
    code_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OwnerEnrollmentToken(Base):
    """A one-time passkey enrollment link printed by ``homelab-harness-owner enroll``."""

    __tablename__ = "owner_enrollment_tokens"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    token_hash: Mapped[str] = mapped_column(String(HASH_LEN), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebAuthnChallenge(Base):
    """A single-use challenge handed to the browser for one WebAuthn ceremony."""

    __tablename__ = "webauthn_challenges"
    __table_args__ = (CheckConstraint("purpose IN ('register', 'login')", name="purpose"),)
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    purpose: Mapped[str] = mapped_column(String(16))
    challenge: Mapped[bytes] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OwnerSession(Base):
    """A logged-in browser session of the owner (the cookie holds the token)."""

    __tablename__ = "owner_sessions"
    __table_args__ = (CheckConstraint("method IN ('passkey', 'recovery_code')", name="method"),)
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    token_hash: Mapped[str] = mapped_column(String(HASH_LEN), unique=True)
    method: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthClient(Base):
    """An OAuth client known to the authorization server.

    ``kind`` is ``cimd`` (the ``client_id`` is the HTTPS URL of its metadata
    document, re-fetched when ``metadata_expires_at`` passes) or ``dcr``
    (registered at ``/oauth/register``). ``audit_id`` is the sanitized label
    used as ``client:<audit_id>`` in the audit log and by ``hh clients``.
    """

    __tablename__ = "oauth_clients"
    __table_args__ = (CheckConstraint("kind IN ('cimd', 'dcr')", name="kind"),)
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    client_id: Mapped[str] = mapped_column(String(CLIENT_ID_MAX), primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))
    audit_id: Mapped[str] = mapped_column(String(AUDIT_ID_MAX), unique=True)
    client_name: Mapped[str] = mapped_column(String(CLIENT_NAME_MAX))
    redirect_uris: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    metadata_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthPendingAuthorization(Base):
    """An authorization request waiting for the owner's consent."""

    __tablename__ = "oauth_pending_authorizations"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="CASCADE")
    )
    redirect_uri: Mapped[str] = mapped_column(Text)
    redirect_uri_explicit: Mapped[bool] = mapped_column(Boolean)
    code_challenge: Mapped[str] = mapped_column(String(128))
    state: Mapped[str | None] = mapped_column(Text)
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    resource: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthGrant(Base):
    """One consented grant: the family that an authorization code and its tokens belong to.

    Revoking the grant ends every access and refresh token issued under it.
    """

    __tablename__ = "oauth_grants"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), index=True
    )
    resource: Mapped[str] = mapped_column(Text)
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(32))


class OAuthAuthorizationCode(Base):
    """An issued authorization code (hashed), single use, bound to PKCE and a redirect URI."""

    __tablename__ = "oauth_authorization_codes"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    code_hash: Mapped[str] = mapped_column(String(HASH_LEN), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="CASCADE")
    )
    redirect_uri: Mapped[str] = mapped_column(Text)
    redirect_uri_explicit: Mapped[bool] = mapped_column(Boolean)
    code_challenge: Mapped[str] = mapped_column(String(128))
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    resource: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("oauth_grants.id", ondelete="CASCADE")
    )


class OAuthToken(Base):
    """An access or refresh token (hashed). A used refresh token has ``used_at`` set."""

    __tablename__ = "oauth_tokens"
    __table_args__ = (CheckConstraint("kind IN ('access', 'refresh')", name="kind"),)
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    token_hash: Mapped[str] = mapped_column(String(HASH_LEN), primary_key=True)
    grant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("oauth_grants.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
