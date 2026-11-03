"""The embedded authorization server's storage and policy, behind the MCP SDK's OAuth handlers.

The SDK's handlers (``mcp.server.auth.handlers``) parse and validate the HTTP
side of ``/oauth/authorize``, ``/oauth/token`` and ``/oauth/revoke``: response
type ``code`` only, PKCE ``S256`` only (a missing ``code_challenge`` or a
``plain`` method is refused), exact redirect URI checks, and the code and
refresh-token expiry checks. This provider is the
``OAuthAuthorizationServerProvider`` they call; it owns everything stateful.

Token design: opaque random tokens, stored as SHA-256 hashes in Postgres, not
JWTs. The resource server is this same process, so validating an opaque token
is one indexed lookup, and revocation (per client, per grant, or on refresh
reuse) takes effect on the very next request. A JWT would need a signing key in
the vault and a revocation list anyway, and would leak its claims to anyone
holding it.

* Access tokens live ``HH_OAUTH_ACCESS_TOKEN_SECONDS`` (15 min by default) and
  are bound to one resource: the canonical ``<public_url>/mcp`` (RFC 8707).
* Refresh tokens rotate on every use. Each grant is a family; presenting a
  refresh token that was already rotated revokes the whole family, since either
  the client or an attacker holds a stolen copy (OAuth 2.1 §4.3.1). A reused
  authorization code revokes the grant it produced (OAuth 2.1 §4.1.3).
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import structlog
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthToken as TokenResponse
from pydantic import AnyUrl
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from homelab_harness.audit.service import AuditWriter
from homelab_harness.auth.cimd import CimdError, CimdFetcher, looks_like_cimd
from homelab_harness.auth.client_rules import (
    HarnessClient,
    cimd_audit_id,
    is_loopback_redirect,
    redirect_host,
)
from homelab_harness.auth.config import CODE_TTL, CONSENT_PATH, PENDING_TTL, SCOPE, AuthConfig
from homelab_harness.auth.models import (
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthGrant,
    OAuthPendingAuthorization,
    OAuthToken,
)
from homelab_harness.auth.owner import hash_token, utc_now

log = structlog.get_logger(__name__)

ACCESS_PREFIX = "hhat_"
REFRESH_PREFIX = "hhrt_"
CODE_PREFIX = "hhac_"
DCR_PREFIX = "dcr:"
_TOKEN_MAX = 128
_STATE_MAX = 1024
_OWNER = "owner"


class ConsentError(Exception):
    """The consent request is unknown, expired or already decided; safe to show."""


class HarnessAccessToken(AccessToken):
    """An access token as the resource server sees it, with its audit label and grant."""

    audit_id: str
    grant_id: uuid.UUID | None = None


class HarnessRefreshToken(RefreshToken):
    """A refresh token with the grant (token family) it belongs to."""

    grant_id: uuid.UUID


class HarnessAuthorizationCode(AuthorizationCode):
    """An authorization code with its stored hash."""

    code_hash: str


@dataclass(frozen=True, slots=True)
class PendingConsent:
    """What the consent screen shows for one authorization request."""

    id: uuid.UUID
    client_id: str
    client_name: str
    kind: str
    redirect_uri: str
    redirect_host: str
    loopback_redirect: bool
    resource: str
    scopes: list[str]


def same_resource(a: str, b: str) -> bool:
    """Compare resource identifiers, tolerating a trailing slash and host case."""

    def canon(value: str) -> str:
        scheme, sep, rest = value.partition("://")
        host, slash, path = rest.partition("/")
        return f"{scheme.lower()}{sep}{host.lower()}{slash}{path}".rstrip("/")

    return canon(a) == canon(b)


def _client_info(row: OAuthClient) -> HarnessClient:
    return HarnessClient.model_validate(
        {
            "client_id": row.client_id,
            "client_name": row.client_name,
            "redirect_uris": row.redirect_uris,
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": SCOPE,
        }
    )


class HarnessOAuthProvider(
    OAuthAuthorizationServerProvider[
        HarnessAuthorizationCode, HarnessRefreshToken, HarnessAccessToken
    ]
):
    """Postgres-backed ``OAuthAuthorizationServerProvider`` for the single owner.

    The identity-assertion grant (SEP-990) keeps the SDK's default: refused.
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        config: AuthConfig,
        audit: AuditWriter,
        fetcher: CimdFetcher,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Create the provider.

        Args:
            sessions: Session factory.
            config: Derived auth configuration.
            audit: Audit writer.
            fetcher: Client ID metadata document fetcher.
            clock: Source of aware UTC time.
        """
        self._sessions = sessions
        self._config = config
        self._audit = audit
        self._fetcher = fetcher
        self._clock = clock

    # --- clients --------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Return a known client, fetching (or re-fetching) a metadata document if needed."""
        if looks_like_cimd(client_id):
            return await self._cimd_client(client_id)
        if not client_id.startswith(DCR_PREFIX) or len(client_id) > 64:
            return None
        async with self._sessions() as session:
            row = await session.get(OAuthClient, client_id)
        return _client_info(row) if row is not None and row.kind == "dcr" else None

    async def _cimd_client(self, client_id: str) -> HarnessClient | None:
        now = self._clock()
        async with self._sessions() as session:
            row = await session.get(OAuthClient, client_id)
        if (
            row is not None
            and row.metadata_expires_at is not None
            and row.metadata_expires_at > now
        ):
            return _client_info(row)
        try:
            doc = await self._fetcher.fetch(client_id)
        except CimdError as exc:
            # The draft says to abort on a failed fetch, even with a stale copy.
            log.info("cimd_client_refused", reason=str(exc))
            return None
        async with self._sessions.begin() as session:
            row = await session.get(OAuthClient, client_id, with_for_update=True)
            if row is None:
                row = OAuthClient(
                    client_id=client_id, kind="cimd", audit_id=cimd_audit_id(client_id)
                )
                session.add(row)
            row.client_name = doc.client_name
            row.redirect_uris = doc.redirect_uris
            row.metadata_expires_at = now + doc.cache_for
            await session.flush()
            return _client_info(row)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Store a dynamically registered client (see :mod:`homelab_harness.auth.dcr`)."""
        async with self._sessions.begin() as session:
            session.add(
                OAuthClient(
                    client_id=client_info.client_id,
                    kind="dcr",
                    audit_id=client_info.client_id,
                    client_name=client_info.client_name or client_info.client_id,
                    redirect_uris=[str(u) for u in client_info.redirect_uris or []],
                )
            )
            await self._audit.record(
                kind="oauth.client_registered",
                actor="system",
                data={"client": client_info.client_id},
                session=session,
            )

    # --- authorization and consent --------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Record the request and send the browser to the consent screen.

        Raises:
            AuthorizeError: ``invalid_target`` for a resource other than this
                harness's ``/mcp``; ``invalid_request`` for malformed PKCE or state.
        """
        resource = params.resource or self._config.resource
        if not same_resource(resource, self._config.resource):
            raise AuthorizeError("invalid_target", "this server only issues tokens for its /mcp")
        if not 43 <= len(params.code_challenge) <= 128:
            raise AuthorizeError("invalid_request", "code_challenge must be an S256 challenge")
        if params.state is not None and len(params.state) > _STATE_MAX:
            raise AuthorizeError("invalid_request", "state is too long")
        async with self._sessions.begin() as session:
            pending = OAuthPendingAuthorization(
                client_id=client.client_id,
                redirect_uri=str(params.redirect_uri),
                redirect_uri_explicit=params.redirect_uri_provided_explicitly,
                code_challenge=params.code_challenge,
                state=params.state,
                scopes=params.scopes or [SCOPE],
                resource=self._config.resource,
                expires_at=self._clock() + PENDING_TTL,
            )
            session.add(pending)
            await session.flush()
            return f"{self._config.url(CONSENT_PATH)}?request={pending.id}"

    async def pending(self, request_id: uuid.UUID) -> PendingConsent:
        """Describe a pending request for the consent screen.

        Raises:
            ConsentError: If it is unknown, expired or already decided.
        """
        async with self._sessions() as session:
            row = await session.get(OAuthPendingAuthorization, request_id)
            if row is None or row.consumed_at is not None or row.expires_at <= self._clock():
                raise ConsentError("this authorization request has expired or was already used")
            client = await session.get(OAuthClient, row.client_id)
            if client is None:
                raise ConsentError("this authorization request has expired or was already used")
            return PendingConsent(
                id=row.id,
                client_id=client.client_id,
                client_name=client.client_name,
                kind=client.kind,
                redirect_uri=row.redirect_uri,
                redirect_host=redirect_host(row.redirect_uri),
                loopback_redirect=is_loopback_redirect(row.redirect_uri),
                resource=row.resource,
                scopes=list(row.scopes),
            )

    async def decide(self, request_id: uuid.UUID, *, approve: bool) -> str:
        """Apply the owner's decision and return where to send the browser.

        Approval issues a single-use authorization code; denial returns
        ``access_denied``. Both include ``iss`` (RFC 9207) and consume the request.

        Raises:
            ConsentError: If the request is unknown, expired or already decided.
        """
        now = self._clock()
        async with self._sessions.begin() as session:
            row = await session.get(OAuthPendingAuthorization, request_id, with_for_update=True)
            if row is None or row.consumed_at is not None or row.expires_at <= now:
                raise ConsentError("this authorization request has expired or was already used")
            row.consumed_at = now
            client = await session.get(OAuthClient, row.client_id)
            audit_id = client.audit_id if client is not None else row.client_id
            if not approve:
                await self._audit.record(
                    kind="oauth.consent_denied",
                    actor=_OWNER,
                    data={"client": audit_id},
                    session=session,
                )
                return construct_redirect_uri(
                    row.redirect_uri,
                    error="access_denied",
                    state=row.state,
                    iss=self._config.issuer,
                )
            code = CODE_PREFIX + secrets.token_urlsafe(32)
            session.add(
                OAuthAuthorizationCode(
                    code_hash=hash_token(code),
                    client_id=row.client_id,
                    redirect_uri=row.redirect_uri,
                    redirect_uri_explicit=row.redirect_uri_explicit,
                    code_challenge=row.code_challenge,
                    scopes=row.scopes,
                    resource=row.resource,
                    expires_at=now + CODE_TTL,
                )
            )
            await self._audit.record(
                kind="oauth.consent_granted",
                actor=_OWNER,
                data={"client": audit_id},
                session=session,
            )
            return construct_redirect_uri(
                row.redirect_uri, code=code, state=row.state, iss=self._config.issuer
            )

    # --- authorization code ---------------------------------------------------

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> HarnessAuthorizationCode | None:
        """Look up an unused code issued to this client; a reused code revokes its grant."""
        if not authorization_code.startswith(CODE_PREFIX) or len(authorization_code) > _TOKEN_MAX:
            return None
        code_hash = hash_token(authorization_code)
        async with self._sessions() as session:
            row = await session.get(OAuthAuthorizationCode, code_hash)
        if row is None or row.client_id != client.client_id:
            return None
        if row.used_at is not None:
            await self._revoke_grant(row.grant_id, reason="code_reuse", client_id=row.client_id)
            return None
        return HarnessAuthorizationCode(
            code=authorization_code,
            code_hash=code_hash,
            scopes=list(row.scopes),
            expires_at=row.expires_at.timestamp(),
            client_id=row.client_id,
            code_challenge=row.code_challenge,
            redirect_uri=AnyUrl(row.redirect_uri),
            redirect_uri_provided_explicitly=row.redirect_uri_explicit,
            resource=row.resource,
            subject=_OWNER,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: HarnessAuthorizationCode
    ) -> TokenResponse:
        """Spend the code (once, even under concurrency) and issue the first token pair.

        Raises:
            TokenError: ``invalid_grant`` if the code was spent concurrently.
        """
        now = self._clock()
        async with self._sessions.begin() as session:
            spent = await session.scalar(
                update(OAuthAuthorizationCode)
                .where(
                    OAuthAuthorizationCode.code_hash == authorization_code.code_hash,
                    OAuthAuthorizationCode.used_at.is_(None),
                )
                .values(used_at=now)
                .returning(OAuthAuthorizationCode.code_hash)
            )
            if spent is None:
                raise TokenError("invalid_grant", "authorization code was already used")
            grant = OAuthGrant(
                client_id=client.client_id,
                resource=authorization_code.resource or self._config.resource,
                scopes=authorization_code.scopes,
            )
            session.add(grant)
            await session.flush()
            await session.execute(
                update(OAuthAuthorizationCode)
                .where(OAuthAuthorizationCode.code_hash == authorization_code.code_hash)
                .values(grant_id=grant.id)
            )
            tokens = await self._issue(session, grant)
            await self._prune(session, now)
            audit_id = await self._audit_id(session, client.client_id)
            await self._audit.record(
                kind="oauth.grant_created",
                actor=f"client:{audit_id}",
                data={"grant": str(grant.id)},
                session=session,
            )
            return tokens

    # --- refresh tokens -------------------------------------------------------

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> HarnessRefreshToken | None:
        """Look up a live refresh token of this client; a rotated one revokes its family."""
        if not refresh_token.startswith(REFRESH_PREFIX) or len(refresh_token) > _TOKEN_MAX:
            return None
        async with self._sessions() as session:
            found = (
                await session.execute(
                    select(OAuthToken, OAuthGrant)
                    .join(OAuthGrant, OAuthGrant.id == OAuthToken.grant_id)
                    .where(
                        OAuthToken.token_hash == hash_token(refresh_token),
                        OAuthToken.kind == "refresh",
                    )
                )
            ).first()
        if found is None:
            return None
        row, grant = found
        if grant.client_id != client.client_id or grant.revoked_at is not None:
            return None
        if row.used_at is not None:
            await self._revoke_grant(grant.id, reason="refresh_reuse", client_id=grant.client_id)
            return None
        return HarnessRefreshToken(
            token=refresh_token,
            client_id=grant.client_id,
            scopes=list(grant.scopes),
            expires_at=int(row.expires_at.timestamp()),
            resource=grant.resource,
            subject=_OWNER,
            grant_id=grant.id,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: HarnessRefreshToken,
        scopes: list[str],
    ) -> TokenResponse:
        """Rotate: spend the refresh token and issue a new access and refresh token.

        Raises:
            TokenError: ``invalid_grant`` if the token was spent concurrently
                (the family is revoked) or the grant was revoked meanwhile.
        """
        now = self._clock()
        async with self._sessions.begin() as session:
            grant = await session.get(OAuthGrant, refresh_token.grant_id, with_for_update=True)
            spent = await session.scalar(
                update(OAuthToken)
                .where(
                    OAuthToken.token_hash == hash_token(refresh_token.token),
                    OAuthToken.kind == "refresh",
                    OAuthToken.used_at.is_(None),
                )
                .values(used_at=now)
                .returning(OAuthToken.token_hash)
            )
            if grant is None or grant.revoked_at is not None:
                raise TokenError("invalid_grant", "refresh token is not valid")
            if spent is None:
                grant.revoked_at = now
                grant.revoke_reason = "refresh_reuse"
                await session.flush()
                await self._record_revocation(session, grant, reason="refresh_reuse")
                # Commit the revocation, then refuse: raising here would roll it back.
                result: TokenResponse | None = None
            else:
                result = await self._issue(session, grant, scopes=scopes)
        if result is None:
            raise TokenError("invalid_grant", "refresh token was already used")
        return result

    # --- access tokens and revocation -----------------------------------------

    async def load_access_token(self, token: str) -> HarnessAccessToken | None:
        """Return the principal of a live access token, or ``None``.

        The caller (:class:`homelab_harness.mcp.auth.HarnessTokenVerifier`)
        checks that its resource is this harness's ``/mcp``.
        """
        if not token.startswith(ACCESS_PREFIX) or len(token) > _TOKEN_MAX:
            return None
        now = self._clock()
        async with self._sessions() as session:
            found = (
                await session.execute(
                    select(OAuthToken.expires_at, OAuthGrant, OAuthClient.audit_id)
                    .join(OAuthGrant, OAuthGrant.id == OAuthToken.grant_id)
                    .join(OAuthClient, OAuthClient.client_id == OAuthGrant.client_id)
                    .where(
                        OAuthToken.token_hash == hash_token(token),
                        OAuthToken.kind == "access",
                        OAuthToken.expires_at > now,
                        OAuthGrant.revoked_at.is_(None),
                    )
                )
            ).first()
        if found is None:
            return None
        expires_at, grant, audit_id = found
        return HarnessAccessToken(
            token="[access-token]",  # noqa: S106 - a label; the raw token is not kept
            client_id=grant.client_id,
            scopes=list(grant.scopes),
            expires_at=int(expires_at.timestamp()),
            resource=grant.resource,
            subject=_OWNER,
            claims={"iss": self._config.issuer},
            audit_id=audit_id,
            grant_id=grant.id,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """RFC 7009 revocation: revoking either token ends its whole grant."""
        grant_id = getattr(token, "grant_id", None)
        if isinstance(grant_id, uuid.UUID):
            await self._revoke_grant(grant_id, reason="client_revoked", client_id=token.client_id)

    # --- helpers --------------------------------------------------------------

    async def _issue(
        self, session: AsyncSession, grant: OAuthGrant, *, scopes: list[str] | None = None
    ) -> TokenResponse:
        now = self._clock()
        access = ACCESS_PREFIX + secrets.token_urlsafe(32)
        refresh = REFRESH_PREFIX + secrets.token_urlsafe(32)
        session.add_all(
            [
                OAuthToken(
                    token_hash=hash_token(access),
                    grant_id=grant.id,
                    kind="access",
                    expires_at=now + self._config.access_token_ttl,
                ),
                OAuthToken(
                    token_hash=hash_token(refresh),
                    grant_id=grant.id,
                    kind="refresh",
                    expires_at=now + self._config.refresh_token_ttl,
                ),
            ]
        )
        await session.flush()
        return TokenResponse(
            access_token=access,
            expires_in=int(self._config.access_token_ttl.total_seconds()),
            scope=" ".join(scopes or grant.scopes),
            refresh_token=refresh,
        )

    async def _revoke_grant(
        self, grant_id: uuid.UUID | None, *, reason: str, client_id: str
    ) -> None:
        if grant_id is None:
            log.warning("oauth_code_reuse", client_id=client_id)
            return
        async with self._sessions.begin() as session:
            grant = await session.get(OAuthGrant, grant_id, with_for_update=True)
            if grant is None or grant.revoked_at is not None:
                return
            grant.revoked_at = self._clock()
            grant.revoke_reason = reason
            await session.flush()
            await self._record_revocation(session, grant, reason=reason)

    async def _record_revocation(
        self, session: AsyncSession, grant: OAuthGrant, *, reason: str
    ) -> None:
        audit_id = await self._audit_id(session, grant.client_id)
        log.warning("oauth_grant_revoked", client_id=audit_id, reason=reason)
        await self._audit.record(
            kind="oauth.grant_revoked",
            actor="system",
            data={"client": audit_id, "grant": str(grant.id), "reason": reason},
            session=session,
        )

    async def _audit_id(self, session: AsyncSession, client_id: str) -> str:
        audit_id = await session.scalar(
            select(OAuthClient.audit_id).where(OAuthClient.client_id == client_id)
        )
        return audit_id or client_id

    async def _prune(self, session: AsyncSession, now: datetime) -> None:
        # Housekeeping on each new grant: expired rows can never be used again.
        await session.execute(delete(OAuthToken).where(OAuthToken.expires_at < now))
        await session.execute(
            delete(OAuthPendingAuthorization).where(OAuthPendingAuthorization.expires_at < now)
        )
        await session.execute(
            delete(OAuthAuthorizationCode).where(
                OAuthAuthorizationCode.expires_at < now - self._config.refresh_token_ttl
            )
        )
