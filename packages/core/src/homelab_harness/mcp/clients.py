"""Client registrations: one bearer token per client (legacy for AI clients; see ADR-0007).

Each AI client (Claude Code, Codex …) gets its own ``client_id`` and token, so
audit can tell clients apart and one can be revoked alone. Only a SHA-256 hash
of the token is stored.

Every client has a role, and the roles are disjoint:

* ``mcp`` tokens authenticate ``/mcp`` and nothing else. They go into AI clients.
* ``owner`` tokens authenticate the owner REST API (``/api/...``) used by ``hh``,
  which manages the vault, and are refused at ``/mcp``. Keeping them apart means
  a token pasted into an AI client can never add, rotate or delete a secret.

Why SHA-256 and not a password hash (argon2, scrypt): the token is 256 bits
from :func:`secrets.token_urlsafe`, not a human-chosen password, so there is
nothing for a slow hash to protect against. Guessing it is infeasible at any
speed. A fast, unsalted hash also lets the lookup be an indexed equality on
``token_hash``, which a salted hash would not allow.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, String, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from homelab_harness.db.base import Base
from homelab_harness_sdk.errors import Conflict, InvalidInput, NotFound

TOKEN_PREFIX = "hhmcp_"  # noqa: S105 - a public prefix, not a credential
"""Prefix of every client token, so secret scanners and humans can recognise one."""

CLIENT_ID_MAX = 64
_CLIENT_ID = re.compile(rf"^[a-z0-9][a-z0-9._-]{{0,{CLIENT_ID_MAX - 1}}}$")
_TOKEN_MAX = 128


class ClientRole(StrEnum):
    """What a client's token may call."""

    MCP = "mcp"
    OWNER = "owner"


_ROLE_VALUES = ", ".join(f"'{r.value}'" for r in ClientRole)


class McpClient(Base):
    """One registered client, its role and the hash of its current token."""

    __tablename__ = "mcp_clients"
    __table_args__ = (CheckConstraint(f"role IN ({_ROLE_VALUES})", name="role"),)
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy reads a plain dict

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    client_id: Mapped[str] = mapped_column(String(CLIENT_ID_MAX), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(16), server_default=ClientRole.MCP.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True, slots=True)
class ClientInfo:
    """A client registration as shown to the owner (no hash, no token)."""

    client_id: str
    role: ClientRole
    created_at: datetime
    revoked_at: datetime | None


def generate_token() -> str:
    """Return a new random client token (prefix plus 256 random bits)."""
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Return the hex SHA-256 of a token, as stored in ``token_hash``."""
    return hashlib.sha256(token.encode()).hexdigest()


def validate_client_id(client_id: str) -> str:
    """Return ``client_id`` if it is a lowercase label such as ``claude-code``.

    Raises:
        InvalidInput: If it is not.
    """
    if not _CLIENT_ID.match(client_id):
        raise InvalidInput("client id must be lowercase letters, digits, '.', '_' or '-'")
    return client_id


async def create_client(
    session: AsyncSession,
    *,
    client_id: str,
    rotate: bool = False,
    role: ClientRole = ClientRole.MCP,
) -> str:
    """Register a client, or give an existing one a new token, and return the token.

    The token is returned once and never stored. Rotating replaces the hash, so
    the previous token stops working at once, and clears a revocation. A
    rotation never changes the role.

    Args:
        session: An open session; the caller commits.
        client_id: The client's label.
        rotate: Replace the token of an existing client instead of refusing.
        role: What the token may call; see the module docstring.

    Returns:
        The new token.

    Raises:
        InvalidInput: If the client id is malformed.
        Conflict: If the client exists and ``rotate`` is false, or ``role``
            differs from the existing client's role.
    """
    validate_client_id(client_id)
    token = generate_token()
    existing = await session.scalar(
        select(McpClient).where(McpClient.client_id == client_id).with_for_update()
    )
    if existing is None:
        session.add(McpClient(client_id=client_id, token_hash=hash_token(token), role=role))
    elif not rotate:
        raise Conflict(f"client {client_id!r} already exists; use --rotate for a new token")
    elif existing.role != role:
        raise Conflict(f"client {client_id!r} has role {existing.role}; roles do not change")
    else:
        existing.token_hash = hash_token(token)
        existing.revoked_at = None
        existing.created_at = func.now()  # pyright: ignore[reportAttributeAccessIssue]
    await session.flush()
    return token


async def revoke_client(session: AsyncSession, *, client_id: str) -> None:
    """Revoke a client's token; its requests get 401 from then on.

    Args:
        session: An open session; the caller commits.
        client_id: The client's label.

    Raises:
        NotFound: If no such client exists.
    """
    row = await session.scalar(
        select(McpClient).where(McpClient.client_id == client_id).with_for_update()
    )
    if row is None:
        raise NotFound(f"no client {client_id!r}")
    if row.revoked_at is None:
        row.revoked_at = func.now()  # pyright: ignore[reportAttributeAccessIssue]
        await session.flush()


async def list_clients(session: AsyncSession) -> list[ClientInfo]:
    """Return every registration, oldest first."""
    rows = await session.scalars(select(McpClient).order_by(McpClient.created_at))
    return [
        ClientInfo(
            client_id=r.client_id,
            role=ClientRole(r.role),
            created_at=r.created_at,
            revoked_at=r.revoked_at,
        )
        for r in rows
    ]


async def client_for_token(
    session: AsyncSession, token: str, *, role: ClientRole = ClientRole.MCP
) -> str | None:
    """Return the client id a token belongs to, if it is valid, unrevoked and has ``role``.

    Args:
        session: An open session.
        token: The presented bearer token.
        role: The role the endpoint requires; a token of the other role is refused.

    Returns:
        The client id, or ``None``.
    """
    if not token.startswith(TOKEN_PREFIX) or len(token) > _TOKEN_MAX:
        return None
    digest = hash_token(token)
    row = await session.scalar(
        select(McpClient).where(
            McpClient.token_hash == digest,
            McpClient.revoked_at.is_(None),
            McpClient.role == role.value,
        )
    )
    # The lookup is by hash; the compare is constant-time anyway, so equality
    # on the stored value never short-circuits on a secret-derived prefix.
    if row is None or not hmac.compare_digest(row.token_hash, digest):
        return None
    return row.client_id
