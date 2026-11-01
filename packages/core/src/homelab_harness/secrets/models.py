"""The vault's tables: ``secrets`` (plain metadata) and ``secret_versions`` (sealed values).

A ``secrets`` row holds only what may be shown: name, kind, description, tags,
dates and the kind's plain metadata (for example an SSH public key or a Proxmox
token id). Every value lives sealed in ``secret_versions``, one row per version,
with the columns :class:`~homelab_harness.secrets.crypto.EncryptedSecret` needs.
Deleting a secret deletes its versions (``ON DELETE CASCADE``), which destroys
every wrapped DEK, so the ciphertext can never be opened again (crypto-shred).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Interval,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from homelab_harness.db.base import Base
from homelab_harness.secrets.crypto import EncryptedSecret
from homelab_harness.secrets.kinds import SecretKind

NAME_MAX = 128
KIND_MAX = 32
SOURCE_MAX = 200
TAG_MAX = 64
KEK_ID_MAX = 64

_KIND_VALUES = ", ".join(f"'{k.value}'" for k in SecretKind)


class Secret(Base):
    """One named secret and its plain metadata. Holds no secret material."""

    __tablename__ = "secrets"
    __table_args__ = (
        CheckConstraint(f"kind IN ({_KIND_VALUES})", name="kind"),
        CheckConstraint("current_version >= 1", name="current_version"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy reads a plain dict

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(NAME_MAX), unique=True)
    kind: Mapped[str] = mapped_column(String(KIND_MAX))
    description: Mapped[str] = mapped_column(Text, server_default="")
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(TAG_MAX)), server_default=text("'{}'::varchar[]")
    )
    source: Mapped[str] = mapped_column(String(SOURCE_MAX), server_default="local")
    # "metadata" is reserved on declarative classes, so the attribute is named meta.
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotate_every: Mapped[timedelta | None] = mapped_column(Interval)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_version: Mapped[int] = mapped_column(Integer)


class SecretVersion(Base):
    """One sealed version of a secret: ciphertext and its wrapped data key."""

    __tablename__ = "secret_versions"
    __table_args__ = (
        UniqueConstraint("secret_id", "version"),
        CheckConstraint("version >= 1", name="version"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy reads a plain dict

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    secret_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("secrets.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    dek_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    # Indexed: KEK rotation looks up every version not yet on the current KEK.
    kek_id: Mapped[str] = mapped_column(String(KEK_ID_MAX), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def sealed(self, *, kind: str) -> EncryptedSecret:
        """Return the stored record in the form :mod:`~homelab_harness.secrets.crypto` opens.

        Args:
            kind: The parent secret's kind, which the AAD binds.

        Returns:
            The sealed record; ``secret_id`` is the parent's UUID as text.
        """
        return EncryptedSecret(
            ciphertext=self.ciphertext,
            nonce=self.nonce,
            wrapped_dek=self.wrapped_dek,
            dek_nonce=self.dek_nonce,
            kek_id=self.kek_id,
            version=self.version,
            kind=kind,
            secret_id=str(self.secret_id),
        )
