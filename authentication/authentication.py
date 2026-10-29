import logging
import uuid
from dataclasses import dataclass

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import authentication, exceptions

User = get_user_model()
logger = logging.getLogger(__name__)


def _decode_access_token(token: str) -> dict:
    """Decode and validate a Supabase JWT.

    Args:
        token: Raw bearer token from the Authorization header.

    Returns:
        Decoded JWT claims.
    """
    decode_kwargs = {
        "algorithms": ["HS256"],
        "issuer": settings.SUPABASE_JWT_ISSUER,
        "options": {"require": ["exp", "iat", "sub"]},
    }

    decode_kwargs["audience"] = settings.SUPABASE_JWT_AUDIENCE or "authenticated"

    return jwt.decode(token, settings.SUPABASE_JWT_SECRET, **decode_kwargs)


class SupabaseUserSyncConflict(Exception):
    """Raised when token claims conflict with an existing user identity."""


@dataclass(frozen=True)
class _SupabaseIdentity:
    uid: uuid.UUID
    email: str | None

    @classmethod
    def from_claims(cls, supabase_uid: str, token_email: str | None):
        """Build a normalized identity from token claims.

        Args:
            supabase_uid: Supabase Auth user ID from the JWT `sub` claim.
            token_email: Optional email claim from the JWT.

        Returns:
            Normalized Supabase identity object.
        """
        return cls(
            uid=uuid.UUID(str(supabase_uid)),
            email=_normalize_token_email(token_email),
        )

    @property
    def row_email(self) -> str:
        """Return the email value to store on the local user row.

        Returns:
            Token email when present, otherwise a deterministic synthetic email.
        """
        return self.email or f"{self.uid}@users.invalid"


def _normalize_token_email(email: str | None) -> str | None:
    """Normalize a JWT email claim using Django's user manager.

    Args:
        email: Email claim from the Supabase JWT.

    Returns:
        Normalized email, or None when no email is present.
    """
    if not email:
        return None
    return User.objects.normalize_email(email)


def _locked_user_by_uid(identity: _SupabaseIdentity):
    """Load a user row by Supabase UID with a transaction lock.

    Args:
        identity: Normalized Supabase identity.

    Returns:
        Matching user row, or None.
    """
    return (
        User.objects.select_for_update()
        .filter(supabase_uid=identity.uid)
        .first()
    )


def _locked_email_owner(email: str, excluded_user_pk):
    """Find another locked user row that owns an email.

    Args:
        email: Normalized email to check.
        excluded_user_pk: User primary key to ignore.

    Returns:
        Conflicting user row, or None.
    """
    return (
        User.objects.select_for_update()
        .filter(email=email)
        .exclude(pk=excluded_user_pk)
        .first()
    )


def _sync_existing_uid_user(user, identity: _SupabaseIdentity):
    """Reconcile email changes for an existing Supabase-linked user.

    Args:
        user: Existing local user row for the Supabase UID.
        identity: Normalized Supabase identity from the current token.

    Returns:
        Updated or unchanged user row.
    """
    if identity.email is None or user.email == identity.email:
        return user

    if _locked_email_owner(identity.email, user.pk) is not None:
        raise SupabaseUserSyncConflict(
            "email is already bound to a different Supabase identity"
        )

    user.email = identity.email
    user.save(update_fields=["email"])
    return user


def _sync_user_once(identity: _SupabaseIdentity):
    """Synchronize one Supabase identity inside a single transaction.

    Args:
        identity: Normalized Supabase identity from the current token.

    Returns:
        Existing or newly-created local user row.
    """
    with transaction.atomic():
        user = _locked_user_by_uid(identity)
        if user is not None:
            return _sync_existing_uid_user(user, identity)

        return User.objects.create_user(
            email=identity.row_email,
            supabase_uid=identity.uid,
        )


def _sync_user_from_supabase_claims(supabase_uid: str, token_email: str | None):
    """Synchronize a local Django user from Supabase JWT claims.

    Args:
        supabase_uid: Supabase Auth user ID from the JWT `sub` claim.
        token_email: Optional email claim from the JWT.

    Returns:
        Local Django user row.
    """
    identity = _SupabaseIdentity.from_claims(supabase_uid, token_email)

    try:
        return _sync_user_once(identity)
    except IntegrityError:
        logger.warning(
            "Supabase user sync hit a uniqueness conflict; retrying once uid=%s email=%s",
            identity.uid,
            identity.email,
        )
        try:
            return _sync_user_once(identity)
        except IntegrityError as retry_exc:
            raise SupabaseUserSyncConflict(
                "database uniqueness conflict during Supabase user sync"
            ) from retry_exc


class SupabaseAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        """Authenticate a DRF request using a Supabase bearer token.

        Args:
            request: Incoming DRF request.

        Returns:
            `(user, None)` when authenticated, None when no bearer token is present.
        """
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None  # No credentials, DRF continues to next auth class

        token = auth_header.split(" ")[1]

        try:
            payload = _decode_access_token(token)
            supabase_uid = payload.get("sub")
            if not supabase_uid:
                raise exceptions.AuthenticationFailed("Invalid Supabase token")

            user = _sync_user_from_supabase_claims(supabase_uid, payload.get("email"))

            return (user, None)

        except SupabaseUserSyncConflict as exc:
            logger.warning(
                "Supabase user sync conflict uid=%s email=%s detail=%s",
                payload.get("sub"),
                payload.get("email"),
                exc,
            )
            raise exceptions.AuthenticationFailed("Invalid or expired token")
        except jwt.ExpiredSignatureError:
            logger.warning("Supabase JWT verification failed: token expired")
            raise exceptions.AuthenticationFailed("Invalid or expired token")
        except jwt.InvalidIssuerError as exc:
            logger.warning("Supabase JWT verification failed: invalid issuer: %s", exc)
            raise exceptions.AuthenticationFailed("Invalid or expired token")
        except jwt.InvalidAudienceError as exc:
            logger.warning("Supabase JWT verification failed: invalid audience: %s", exc)
            raise exceptions.AuthenticationFailed("Invalid or expired token")
        except jwt.InvalidSignatureError as exc:
            logger.warning("Supabase JWT verification failed: invalid signature: %s", exc)
            raise exceptions.AuthenticationFailed("Invalid or expired token")
        except jwt.InvalidTokenError as exc:
            logger.warning(
                "Supabase JWT verification failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            raise exceptions.AuthenticationFailed("Invalid or expired token")
        except Exception as exc:
            logger.exception("Unexpected Supabase auth failure: %s", exc)
            raise exceptions.AuthenticationFailed("Invalid or expired token")
