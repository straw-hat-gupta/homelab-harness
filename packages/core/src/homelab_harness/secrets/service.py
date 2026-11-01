"""The vault service: store, rotate, describe, resolve, revoke, delete and rewrap secrets.

Every operation writes an audit event in the same transaction as the change it
describes. Events carry identifiers only (name, ``vault_id``, kind, version,
consumer, purpose): never a value, a length or a hash (R-34).

:meth:`VaultService.resolve` is the only way to get a value out, and it is for
code inside the harness (the targets file today, ``broker`` executors later).
No REST route or MCP tool calls it.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from homelab_harness.audit.service import AuditWriter
from homelab_harness.secrets.crypto import SecretIntegrityError, rewrap, seal, unseal
from homelab_harness.secrets.keys import KeyProvider, KeyProviderError
from homelab_harness.secrets.kinds import SecretFields, SecretKind, decode_fields, encode_fields
from homelab_harness.secrets.models import Secret, SecretVersion
from homelab_harness.secrets.payloads import carried_metadata, derive_metadata
from homelab_harness_sdk import SECRET_NAME_PATTERN
from homelab_harness_sdk.errors import Conflict, InvalidInput, NotFound

log = structlog.get_logger(__name__)

_NAME = re.compile(SECRET_NAME_PATTERN)
_TAG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_TAGS_MAX = 32
_DESCRIPTION_MAX = 1000
_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}$")


@dataclass(frozen=True, slots=True)
class VersionInfo:
    """One stored version, as the owner sees it (no ciphertext)."""

    version: int
    kek_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SecretInfo:
    """A secret's plain description. Holds no value, length or hash."""

    id: uuid.UUID
    name: str
    kind: SecretKind
    description: str
    tags: tuple[str, ...]
    source: str
    metadata: Mapping[str, Any]
    created_at: datetime
    rotated_at: datetime | None
    expires_at: datetime | None
    rotate_every: timedelta | None
    revoked_at: datetime | None
    current_version: int
    versions: tuple[VersionInfo, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedSecret:
    """A decrypted secret for in-harness use. Its values are wrapped and redacted."""

    name: str
    kind: SecretKind
    version: int
    fields: SecretFields
    metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class RewrapReport:
    """What one ``rewrap_all`` run did.

    Attributes:
        kek_id: The current KEK every version was rewrapped to.
        rewrapped: Versions moved to the current KEK by this run.
        already_current: Versions that were already on it (skipped).
        failed: Versions whose wrapping KEK is missing or whose DEK failed
            authentication; they stay as they were.
    """

    kek_id: str
    rewrapped: int
    already_current: int
    failed: int


def _check_name(name: str) -> str:
    if not _NAME.match(name):
        raise InvalidInput("secret names are lowercase letters, digits, '.', '_' or '-'")
    return name


def _check_label(label: str, *, what: str) -> str:
    if not _LABEL.match(label):
        raise InvalidInput(f"{what} must be an identifier-like label")
    return label


def _check_tags(tags: Sequence[str]) -> list[str]:
    if len(tags) > _TAGS_MAX or not all(_TAG.match(t) for t in tags):
        raise InvalidInput("tags are lowercase labels, at most 32 of them")
    return sorted(set(tags))


def _info(row: Secret, versions: Sequence[SecretVersion] = ()) -> SecretInfo:
    return SecretInfo(
        id=row.id,
        name=row.name,
        kind=SecretKind(row.kind),
        description=row.description,
        tags=tuple(row.tags),
        source=row.source,
        metadata=dict(row.meta),
        created_at=row.created_at,
        rotated_at=row.rotated_at,
        expires_at=row.expires_at,
        rotate_every=row.rotate_every,
        revoked_at=row.revoked_at,
        current_version=row.current_version,
        versions=tuple(
            VersionInfo(version=v.version, kek_id=v.kek_id, created_at=v.created_at)
            for v in versions
        ),
    )


class VaultService:
    """The vault over Postgres, sealing with the configured KEK provider."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        keys: KeyProvider,
        audit: AuditWriter,
    ) -> None:
        """Create the service.

        Args:
            sessions: Session factory for the app's tables.
            keys: KEK provider; its current KEK wraps every new data key.
            audit: Audit writer; every operation records one event.
        """
        self._sessions = sessions
        self._keys = keys
        self._audit = audit

    def _seal_version(
        self, *, secret_id: uuid.UUID, version: int, fields: SecretFields
    ) -> SecretVersion:
        sealed = seal(
            encode_fields(fields),
            secret_id=str(secret_id),
            version=version,
            kind=fields.kind.value,
            kek=self._keys.current(),
        )
        return SecretVersion(
            secret_id=secret_id,
            version=version,
            ciphertext=sealed.ciphertext,
            nonce=sealed.nonce,
            wrapped_dek=sealed.wrapped_dek,
            dek_nonce=sealed.dek_nonce,
            kek_id=sealed.kek_id,
        )

    async def _record(
        self, session: AsyncSession, *, kind: str, actor: str, data: Mapping[str, object]
    ) -> None:
        await self._audit.record(kind=kind, actor=actor, data=data, session=session)

    @staticmethod
    async def _locked(session: AsyncSession, name: str) -> Secret:
        row = await session.scalar(select(Secret).where(Secret.name == name).with_for_update())
        if row is None:
            raise NotFound(f"no secret named {name!r}")
        return row

    async def create(
        self,
        *,
        name: str,
        fields: SecretFields,
        metadata: Mapping[str, Any],
        actor: str,
        description: str = "",
        tags: Sequence[str] = (),
        expires_at: datetime | None = None,
        rotate_every: timedelta | None = None,
    ) -> SecretInfo:
        """Store a new secret as version 1.

        Args:
            name: Unique name, used in ``secret://<name>`` handles.
            fields: The validated value (its kind is the secret's kind).
            metadata: The owner's plain metadata input for the kind.
            actor: Audit actor, ``owner`` for the owner API.
            description: Free text shown with the secret.
            tags: Lowercase labels.
            expires_at: When the value stops working, if known (aware).
            rotate_every: Reminder interval for rotation, if any.

        Returns:
            The stored secret's description.

        Raises:
            InvalidInput: If a field breaks the rules.
            Conflict: If the name is taken.
        """
        _check_name(name)
        clean_tags = _check_tags(tags)
        if len(description) > _DESCRIPTION_MAX:
            raise InvalidInput(f"description is limited to {_DESCRIPTION_MAX} characters")
        if rotate_every is not None and rotate_every <= timedelta(0):
            raise InvalidInput("rotate_every must be positive")
        kind = fields.kind
        meta = derive_metadata(kind, fields, metadata)
        secret_id = uuid.uuid4()
        row = Secret(
            id=secret_id,
            name=name,
            kind=kind.value,
            description=description,
            tags=clean_tags,
            source="local",
            meta=meta.model_dump(mode="json"),
            expires_at=expires_at,
            rotate_every=rotate_every,
            current_version=1,
        )
        version = self._seal_version(secret_id=secret_id, version=1, fields=fields)
        try:
            async with self._sessions.begin() as session:
                session.add(row)
                await session.flush()
                session.add(version)
                await session.flush()
                await self._record(
                    session,
                    kind="secret.created",
                    actor=actor,
                    data={
                        "name": name,
                        "vault_id": str(secret_id),
                        "kind": kind.value,
                        "version": 1,
                    },
                )
        except IntegrityError:
            raise Conflict(f"a secret named {name!r} already exists") from None
        log.info("secret_created", name=name, kind=kind.value)
        return _info(row, [version])

    async def add_version(
        self,
        *,
        name: str,
        fields: SecretFields,
        actor: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> SecretInfo:
        """Rotate a secret: store a new value as the next version.

        Older versions are kept. A revoked secret becomes usable again, since a
        new value is what revocation usually waits for.

        Args:
            name: The secret.
            fields: The new value; must be of the secret's kind.
            actor: Audit actor.
            metadata: New plain metadata; when omitted, the previous metadata is
                kept and the derived parts are recomputed from the new value.

        Returns:
            The updated description.

        Raises:
            NotFound: If there is no such secret.
            InvalidInput: If the kind differs or the metadata is invalid.
        """
        async with self._sessions.begin() as session:
            row = await self._locked(session, name)
            kind = SecretKind(row.kind)
            if fields.kind is not kind:
                raise InvalidInput(f"secret {name!r} is a {kind}, not a {fields.kind}")
            base = metadata if metadata is not None else carried_metadata(kind, row.meta)
            meta = derive_metadata(kind, fields, base)
            next_version = row.current_version + 1
            session.add(self._seal_version(secret_id=row.id, version=next_version, fields=fields))
            row.current_version = next_version
            row.meta = meta.model_dump(mode="json")
            row.rotated_at = func.now()  # pyright: ignore[reportAttributeAccessIssue]
            row.revoked_at = None
            await session.flush()
            await session.refresh(row)
            await self._record(
                session,
                kind="secret.rotated",
                actor=actor,
                data={
                    "name": name,
                    "vault_id": str(row.id),
                    "kind": kind.value,
                    "version": next_version,
                },
            )
            versions = await self._versions(session, row.id)
        log.info("secret_rotated", name=name, version=next_version)
        return _info(row, versions)

    @staticmethod
    async def _versions(session: AsyncSession, secret_id: uuid.UUID) -> list[SecretVersion]:
        rows = await session.scalars(
            select(SecretVersion)
            .where(SecretVersion.secret_id == secret_id)
            .order_by(SecretVersion.version)
        )
        return list(rows)

    async def get_metadata(self, *, name: str) -> SecretInfo:
        """Describe one secret, with its versions.

        Args:
            name: The secret.

        Returns:
            The description; no values.

        Raises:
            NotFound: If there is no such secret.
        """
        async with self._sessions() as session:
            row = await session.scalar(select(Secret).where(Secret.name == name))
            if row is None:
                raise NotFound(f"no secret named {name!r}")
            return _info(row, await self._versions(session, row.id))

    async def list_secrets(self) -> list[SecretInfo]:
        """Describe every secret, by name, without version details."""
        async with self._sessions() as session:
            rows = await session.scalars(select(Secret).order_by(Secret.name))
            return [_info(r) for r in rows]

    async def resolve(self, *, name: str, consumer: str, purpose: str) -> ResolvedSecret:
        """Decrypt the current version for use inside the harness, and audit the use.

        Args:
            name: The secret.
            consumer: Who uses it, for example ``targets:proxmox/home/read``.
            purpose: Why, for example ``target-credential``.

        Returns:
            The decrypted fields; every value is wrapped and registered with the
            redactor.

        Raises:
            NotFound: If there is no such secret.
            Conflict: If it is revoked.
            InvalidInput: If ``consumer`` or ``purpose`` is not a label.
            KeyProviderError: If the KEK that wrapped it is not loaded.
            SecretIntegrityError: If the stored record fails authentication.
        """
        _check_label(consumer, what="consumer")
        _check_label(purpose, what="purpose")
        async with self._sessions.begin() as session:
            row = await session.scalar(select(Secret).where(Secret.name == name))
            if row is None:
                raise NotFound(f"no secret named {name!r}")
            if row.revoked_at is not None:
                raise Conflict(f"secret {name!r} is revoked; rotate it to use it again")
            version = await session.scalar(
                select(SecretVersion).where(
                    SecretVersion.secret_id == row.id,
                    SecretVersion.version == row.current_version,
                )
            )
            if version is None:  # pragma: no cover - the transaction that rotates writes both
                raise SecretIntegrityError("current version is missing")
            kind = SecretKind(row.kind)
            sealed = version.sealed(kind=kind.value)
            fields = decode_fields(kind, unseal(sealed, kek=self._keys.get(sealed.kek_id)))
            await self._record(
                session,
                kind="secret.used",
                actor="system",
                data={
                    "name": name,
                    "vault_id": str(row.id),
                    "version": row.current_version,
                    "consumer": consumer,
                    "purpose": purpose,
                },
            )
        return ResolvedSecret(
            name=name,
            kind=kind,
            version=row.current_version,
            fields=fields,
            metadata=dict(row.meta),
        )

    async def revoke(self, *, name: str, actor: str) -> SecretInfo:
        """Make a secret unusable until it is rotated. Idempotent.

        Args:
            name: The secret.
            actor: Audit actor.

        Returns:
            The updated description.

        Raises:
            NotFound: If there is no such secret.
        """
        async with self._sessions.begin() as session:
            row = await self._locked(session, name)
            if row.revoked_at is None:
                row.revoked_at = func.now()  # pyright: ignore[reportAttributeAccessIssue]
                await session.flush()
                await session.refresh(row)
                await self._record(
                    session,
                    kind="secret.revoked",
                    actor=actor,
                    data={"name": name, "vault_id": str(row.id)},
                )
            return _info(row)

    async def delete(self, *, name: str, confirm_name: str, actor: str) -> int:
        """Crypto-shred a secret: delete every version's ciphertext and wrapped DEK.

        Args:
            name: The secret.
            confirm_name: Must equal ``name`` (typed confirmation).
            actor: Audit actor.

        Returns:
            How many versions were destroyed.

        Raises:
            InvalidInput: If the confirmation does not match.
            NotFound: If there is no such secret.
        """
        if confirm_name != name:
            raise InvalidInput("the confirmation must repeat the secret's name exactly")
        async with self._sessions.begin() as session:
            row = await self._locked(session, name)
            result = await session.execute(
                delete(SecretVersion).where(SecretVersion.secret_id == row.id)
            )
            shredded: int = getattr(result, "rowcount", 0)
            await session.delete(row)
            await session.flush()
            await self._record(
                session,
                kind="secret.deleted",
                actor=actor,
                data={
                    "name": name,
                    "vault_id": str(row.id),
                    "kind": row.kind,
                    "versions_destroyed": shredded,
                },
            )
        log.info("secret_deleted", name=name, versions=shredded)
        return shredded

    async def rewrap_all(self, *, actor: str) -> RewrapReport:
        """Rewrap every data key under the current KEK, leaving ciphertext untouched.

        Each version is rewrapped in its own transaction, so an interrupted run
        keeps what it finished, and running again picks up the rest. Versions
        already on the current KEK are skipped, so a rerun changes nothing.

        Args:
            actor: Audit actor.

        Returns:
            Counts of rewrapped, skipped and failed versions.
        """
        current = self._keys.current()
        async with self._sessions() as session:
            already = await session.scalar(
                select(func.count())
                .select_from(SecretVersion)
                .where(SecretVersion.kek_id == current.kek_id)
            )
            pending = list(
                await session.scalars(
                    select(SecretVersion.id)
                    .where(SecretVersion.kek_id != current.kek_id)
                    .order_by(SecretVersion.created_at)
                )
            )
        outcomes = [await self._rewrap_one(version_id) for version_id in pending]
        report = RewrapReport(
            kek_id=current.kek_id,
            rewrapped=outcomes.count("rewrapped"),
            already_current=(already or 0) + outcomes.count("current"),
            failed=outcomes.count("failed"),
        )
        await self._audit.record(
            kind="vault.kek_rotated",
            actor=actor,
            data={
                "kek_id": report.kek_id,
                "rewrapped": report.rewrapped,
                "already_current": report.already_current,
                "failed": report.failed,
            },
        )
        log.info(
            "vault_rewrapped",
            kek_id=report.kek_id,
            rewrapped=report.rewrapped,
            already_current=report.already_current,
            failed=report.failed,
        )
        return report

    async def _rewrap_one(self, version_id: uuid.UUID) -> str:
        current = self._keys.current()
        async with self._sessions.begin() as session:
            found = (
                await session.execute(
                    select(SecretVersion, Secret.kind)
                    .join(Secret, Secret.id == SecretVersion.secret_id)
                    .where(SecretVersion.id == version_id)
                    .with_for_update(of=SecretVersion)
                )
            ).one_or_none()
            if found is None:
                return "gone"  # deleted since the scan
            version, kind = found
            if version.kek_id == current.kek_id:
                return "current"  # a concurrent run got there first
            try:
                moved = rewrap(
                    version.sealed(kind=kind),
                    old_kek=self._keys.get(version.kek_id),
                    new_kek=current,
                )
            except (KeyProviderError, SecretIntegrityError) as exc:
                log.error(
                    "vault_rewrap_failed",
                    version_id=str(version_id),
                    kek_id=version.kek_id,
                    error_type=type(exc).__name__,
                )
                return "failed"
            version.wrapped_dek = moved.wrapped_dek
            version.dek_nonce = moved.dek_nonce
            version.kek_id = moved.kek_id
        return "rewrapped"

    async def versions_on_other_keks(self) -> int:
        """Count versions not yet wrapped by the current KEK (for readiness)."""
        async with self._sessions() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(SecretVersion)
                .where(SecretVersion.kek_id != self._keys.current().kek_id)
            )
        return count or 0
