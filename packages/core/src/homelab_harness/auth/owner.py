"""The owner's identity: enrollment, passkey and recovery-code login, browser sessions.

There is exactly one owner and no registration endpoint. The owner is created by
``homelab-harness-owner enroll`` on the harness host (host access is the root of
trust), which prints a one-time enrollment link and the recovery codes. Opening
the link registers a passkey. A second ``enroll`` is refused once a passkey
exists; ``--add-passkey`` prints a link that adds another passkey to the same
owner, again only from the host.

Every ceremony is single-use: enrollment tokens, WebAuthn challenges and
recovery codes are consumed in the transaction that checks them, under a row
lock, so a replayed or concurrent request finds them used.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from homelab_harness.audit.service import AuditWriter
from homelab_harness.auth.config import CHALLENGE_TTL, ENROLL_PATH, ENROLLMENT_TTL, AuthConfig
from homelab_harness.auth.models import (
    Owner,
    OwnerEnrollmentToken,
    OwnerPasskey,
    OwnerRecoveryCode,
    OwnerSession,
    WebAuthnChallenge,
)
from homelab_harness.auth.passkeys import (
    PasskeyError,
    authentication_options,
    registration_options,
    verify_authentication,
    verify_registration,
)
from homelab_harness.auth.recovery import generate_codes, hash_secret, split_code, verify_secret
from homelab_harness_sdk.errors import Conflict

log = structlog.get_logger(__name__)

_CHALLENGE_BYTES = 32
_USER_HANDLE_BYTES = 32


class AuthFailed(Exception):
    """A login or enrollment step was refused; the message is safe to show."""


def utc_now() -> datetime:
    """Current aware UTC time (the default clock)."""
    return datetime.now(UTC)


def hash_token(token: str) -> str:
    """Hex SHA-256 of a random token, as stored."""
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token_for(session_token: str) -> str:
    """The CSRF token bound to a session: derived from it, so nothing extra is stored.

    The session token sits in an ``HttpOnly`` cookie, so a page on another
    origin can neither read it nor compute this value.
    """
    return hmac.new(session_token.encode(), b"homelab-harness csrf v1", hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class Enrollment:
    """What ``homelab-harness-owner enroll`` prints."""

    url: str
    expires_at: datetime
    recovery_codes: list[str] | None


@dataclass(frozen=True, slots=True)
class Ceremony:
    """A started WebAuthn ceremony: the challenge's id and the browser options."""

    challenge_id: uuid.UUID
    options: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """A live owner session."""

    id: uuid.UUID
    method: str


class OwnerService:
    """Owner enrollment, login and sessions."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        config: AuthConfig,
        audit: AuditWriter,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Create the service.

        Args:
            sessions: Session factory.
            config: Derived auth configuration.
            audit: Audit writer; enrollment and logins are audited as ``owner``.
            clock: Source of aware UTC time.
        """
        self._sessions = sessions
        self._config = config
        self._audit = audit
        self._clock = clock

    # --- host-side enrollment -------------------------------------------------

    async def start_enrollment(self, *, add_passkey: bool = False) -> Enrollment:
        """Create the owner if needed and return a one-time enrollment link.

        Args:
            add_passkey: Add a passkey to an enrolled owner instead of enrolling.

        Returns:
            The link, its expiry, and (for a first enrollment) new recovery codes.

        Raises:
            Conflict: If an owner is already enrolled and ``add_passkey`` is
                false, or no owner is enrolled and it is true.
        """
        now = self._clock()
        token = secrets.token_urlsafe(32)
        codes: list[str] | None = None
        try:
            async with self._sessions.begin() as session:
                owner = await session.scalar(select(Owner).with_for_update())
                enrolled = owner is not None and owner.enrolled_at is not None
                if enrolled and not add_passkey:
                    raise Conflict(
                        "an owner is already enrolled; there is only one owner. "
                        "Use --add-passkey to add a passkey to it"
                    )
                if not enrolled and add_passkey:
                    raise Conflict("no owner is enrolled yet; run enroll without --add-passkey")
                if owner is None:
                    session.add(Owner(user_handle=secrets.token_bytes(_USER_HANDLE_BYTES)))
                if not enrolled:
                    codes = await _replace_recovery_codes(session)
                # Only the newest link works.
                await session.execute(
                    update(OwnerEnrollmentToken)
                    .where(OwnerEnrollmentToken.used_at.is_(None))
                    .values(used_at=now)
                )
                expires_at = now + ENROLLMENT_TTL
                session.add(
                    OwnerEnrollmentToken(token_hash=hash_token(token), expires_at=expires_at)
                )
                await self._audit.record(
                    kind="owner.enrollment_started",
                    actor="owner",
                    data={"add_passkey": add_passkey},
                    session=session,
                )
        except IntegrityError:
            # Two concurrent first enrollments: the singleton constraint stops the second.
            raise Conflict("another enrollment is in progress; try again") from None
        # The token travels in the fragment, which browsers never send to a server
        # or put in a Referer, so it stays out of access logs and proxies.
        url = f"{self._config.url(ENROLL_PATH)}#token={token}"
        return Enrollment(url=url, expires_at=expires_at, recovery_codes=codes)

    async def regenerate_recovery_codes(self) -> list[str]:
        """Replace every recovery code with ten new ones (host-side).

        Raises:
            Conflict: If no owner is enrolled.
        """
        async with self._sessions.begin() as session:
            owner = await session.scalar(select(Owner).with_for_update())
            if owner is None or owner.enrolled_at is None:
                raise Conflict("no owner is enrolled yet")
            codes = await _replace_recovery_codes(session)
            await self._audit.record(
                kind="owner.recovery_codes_replaced", actor="owner", session=session
            )
        return codes

    # --- browser-side enrollment ----------------------------------------------

    async def enrollment_options(self, token: str) -> Ceremony:
        """Start passkey registration for a valid enrollment link.

        Raises:
            AuthFailed: If the link is unknown, used or expired.
        """
        async with self._sessions.begin() as session:
            await self._live_enrollment_token(session, token, lock=False)
            owner = await session.scalar(select(Owner))
            if owner is None:
                raise AuthFailed("this enrollment link is not valid")
            existing = list(await session.scalars(select(OwnerPasskey.credential_id)))
            challenge = await self._new_challenge(session, "register")
            options = registration_options(
                rp_id=self._config.rp_id,
                user_handle=owner.user_handle,
                challenge=challenge.challenge,
                existing=existing,
            )
            return Ceremony(challenge_id=challenge.id, options=options)

    async def complete_enrollment(
        self, *, token: str, challenge_id: uuid.UUID, credential: dict[str, Any]
    ) -> str:
        """Verify the new passkey, store it, consume the link and log the owner in.

        Returns:
            A new session token for the cookie.

        Raises:
            AuthFailed: If the link, the challenge or the passkey is not valid.
        """
        challenge = await self._consume_challenge(challenge_id, "register")
        async with self._sessions.begin() as session:
            link = await self._live_enrollment_token(session, token, lock=True)
            try:
                passkey = verify_registration(
                    credential=credential,
                    challenge=challenge,
                    rp_id=self._config.rp_id,
                    origin=self._config.origin,
                )
            except PasskeyError as exc:
                raise AuthFailed(str(exc)) from None
            owner = await session.scalar(select(Owner).with_for_update())
            if owner is None:
                raise AuthFailed("this enrollment link is not valid")
            now = self._clock()
            session.add(
                OwnerPasskey(
                    credential_id=passkey.credential_id,
                    public_key=passkey.public_key,
                    sign_count=passkey.sign_count,
                )
            )
            link.used_at = now
            first = owner.enrolled_at is None
            if first:
                owner.enrolled_at = now
            try:
                await session.flush()
            except IntegrityError:
                raise AuthFailed("this passkey is already registered") from None
            await self._audit.record(
                kind="owner.passkey_enrolled",
                actor="owner",
                data={"first": first},
                session=session,
            )
            return await self._create_session(session, method="passkey")

    # --- login ----------------------------------------------------------------

    async def login_options(self) -> Ceremony:
        """Start a passkey login.

        Raises:
            AuthFailed: If no owner is enrolled.
        """
        async with self._sessions.begin() as session:
            allowed = list(await session.scalars(select(OwnerPasskey.credential_id)))
            if not allowed:
                raise AuthFailed("no owner is enrolled; run homelab-harness-owner enroll")
            challenge = await self._new_challenge(session, "login")
            options = authentication_options(
                rp_id=self._config.rp_id, challenge=challenge.challenge, allowed=allowed
            )
            return Ceremony(challenge_id=challenge.id, options=options)

    async def login_with_passkey(
        self, *, challenge_id: uuid.UUID, credential: dict[str, Any]
    ) -> str:
        """Verify a passkey assertion and return a new session token.

        Raises:
            AuthFailed: If the challenge or the assertion is not valid.
        """
        try:
            raw_id = _b64url_decode(str(credential["rawId"]))
        except (KeyError, ValueError):
            raise AuthFailed("the passkey response is malformed") from None
        challenge = await self._consume_challenge(challenge_id, "login")
        async with self._sessions.begin() as session:
            passkey = await session.scalar(
                select(OwnerPasskey).where(OwnerPasskey.credential_id == raw_id).with_for_update()
            )
            if passkey is None:
                raise AuthFailed("this passkey is not registered")
            try:
                new_count = verify_authentication(
                    credential=credential,
                    challenge=challenge,
                    rp_id=self._config.rp_id,
                    origin=self._config.origin,
                    public_key=passkey.public_key,
                    sign_count=passkey.sign_count,
                )
            except PasskeyError as exc:
                raise AuthFailed(str(exc)) from None
            passkey.sign_count = new_count
            passkey.last_used_at = self._clock()
            await self._audit.record(
                kind="owner.login", actor="owner", data={"method": "passkey"}, session=session
            )
            return await self._create_session(session, method="passkey")

    async def login_with_recovery_code(self, code: str) -> str:
        """Spend one recovery code and return a new session token.

        Raises:
            AuthFailed: If the code is malformed, unknown or already used.
        """
        parts = split_code(code)
        refused = AuthFailed("that recovery code is not valid")
        if parts is None:
            raise refused
        lookup, secret = parts
        async with self._sessions.begin() as session:
            row = await session.scalar(
                select(OwnerRecoveryCode)
                .where(OwnerRecoveryCode.lookup == lookup, OwnerRecoveryCode.used_at.is_(None))
                .with_for_update()
            )
            enrolled = await session.scalar(select(Owner.enrolled_at))
            # scrypt is CPU-bound; keep the event loop free while it runs.
            if (
                row is None
                or enrolled is None
                or not await asyncio.to_thread(verify_secret, secret, row.code_hash)
            ):
                raise refused
            row.used_at = self._clock()
            remaining = await session.scalar(
                select(func.count())
                .select_from(OwnerRecoveryCode)
                .where(OwnerRecoveryCode.used_at.is_(None), OwnerRecoveryCode.id != row.id)
            )
            await self._audit.record(
                kind="owner.login",
                actor="owner",
                data={"method": "recovery_code", "codes_left": remaining or 0},
                session=session,
            )
            log.warning("owner_recovery_code_used", codes_left=remaining or 0)
            return await self._create_session(session, method="recovery_code")

    # --- sessions -------------------------------------------------------------

    async def session_for(self, token: str | None) -> SessionInfo | None:
        """Return the live session a cookie names, sliding its idle timeout.

        Args:
            token: The cookie value, if any.

        Returns:
            The session, or ``None`` if missing, unknown, revoked, idle too long
            or past its absolute lifetime.
        """
        if not token or len(token) > 128:
            return None
        now = self._clock()
        async with self._sessions.begin() as session:
            row = await session.scalar(
                select(OwnerSession).where(
                    OwnerSession.token_hash == hash_token(token),
                    OwnerSession.revoked_at.is_(None),
                )
            )
            if row is None or row.expires_at <= now:
                return None
            if now - row.last_seen_at > self._config.session_idle:
                row.revoked_at = now
                return None
            row.last_seen_at = now
            return SessionInfo(id=row.id, method=row.method)

    async def logout(self, token: str) -> None:
        """End the session a cookie names (no-op if it is already gone)."""
        async with self._sessions.begin() as session:
            await session.execute(
                update(OwnerSession)
                .where(OwnerSession.token_hash == hash_token(token))
                .values(revoked_at=self._clock())
            )

    # --- helpers --------------------------------------------------------------

    async def _create_session(self, session: AsyncSession, *, method: str) -> str:
        now = self._clock()
        token = secrets.token_urlsafe(32)
        session.add(
            OwnerSession(
                token_hash=hash_token(token),
                method=method,
                last_seen_at=now,
                expires_at=now + self._config.session_max,
            )
        )
        # Housekeeping: expired ceremonies and sessions are of no further use.
        horizon = now - CHALLENGE_TTL
        await session.execute(
            delete(WebAuthnChallenge).where(WebAuthnChallenge.expires_at < horizon)
        )
        await session.execute(delete(OwnerSession).where(OwnerSession.expires_at < horizon))
        await session.flush()
        return token

    async def _live_enrollment_token(
        self, session: AsyncSession, token: str, *, lock: bool
    ) -> OwnerEnrollmentToken:
        if not token or len(token) > 128:
            raise AuthFailed("this enrollment link is not valid")
        query = select(OwnerEnrollmentToken).where(
            OwnerEnrollmentToken.token_hash == hash_token(token)
        )
        row = await session.scalar(query.with_for_update() if lock else query)
        if row is None or row.used_at is not None or row.expires_at <= self._clock():
            raise AuthFailed(
                "this enrollment link is not valid (used or expired); "
                "run homelab-harness-owner enroll again on the harness host"
            )
        return row

    async def _new_challenge(self, session: AsyncSession, purpose: str) -> WebAuthnChallenge:
        row = WebAuthnChallenge(
            purpose=purpose,
            challenge=secrets.token_bytes(_CHALLENGE_BYTES),
            expires_at=self._clock() + CHALLENGE_TTL,
        )
        session.add(row)
        await session.flush()
        return row

    async def _consume_challenge(self, challenge_id: uuid.UUID, purpose: str) -> bytes:
        # Its own transaction: a challenge is spent even when verification then fails.
        now = self._clock()
        async with self._sessions.begin() as session:
            challenge = await session.scalar(
                update(WebAuthnChallenge)
                .where(
                    WebAuthnChallenge.id == challenge_id,
                    WebAuthnChallenge.purpose == purpose,
                    WebAuthnChallenge.used_at.is_(None),
                    WebAuthnChallenge.expires_at > now,
                )
                .values(used_at=now)
                .returning(WebAuthnChallenge.challenge)
            )
        if challenge is None:
            raise AuthFailed("this sign-in attempt expired; start again")
        return challenge


async def _replace_recovery_codes(session: AsyncSession) -> list[str]:
    codes = generate_codes()
    parts = [p for p in map(split_code, codes) if p is not None]
    hashed = await asyncio.gather(*(asyncio.to_thread(hash_secret, secret) for _, secret in parts))
    await session.execute(delete(OwnerRecoveryCode))
    for (lookup, _), code_hash in zip(parts, hashed, strict=True):
        session.add(OwnerRecoveryCode(lookup=lookup, code_hash=code_hash))
    await session.flush()
    return codes


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
