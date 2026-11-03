"""WebAuthn ceremonies for the owner's passkeys, on py_webauthn (duo-labs).

A passkey is the owner's only everyday factor, so user verification (PIN or
biometric on the authenticator) is required, not just presence. Attestation is
not requested: the harness does not restrict authenticator models, and asking
for attestation would only add a privacy cost.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

RP_NAME = "homelab-harness"
OWNER_NAME = "owner"
TIMEOUT_MS = 120_000


class PasskeyError(Exception):
    """A WebAuthn response failed verification; the message is safe to show."""


@dataclass(frozen=True, slots=True)
class NewPasskey:
    """A verified registration: what is stored for the credential."""

    credential_id: bytes
    public_key: bytes
    sign_count: int


def registration_options(
    *, rp_id: str, user_handle: bytes, challenge: bytes, existing: Sequence[bytes]
) -> dict[str, Any]:
    """Options for ``navigator.credentials.create()``, as JSON-ready data.

    Args:
        rp_id: Relying party id (the harness host name).
        user_handle: The owner's opaque WebAuthn user id.
        challenge: Fresh random challenge, stored server-side.
        existing: Credential ids already registered, so the same authenticator
            is not enrolled twice.
    """
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_name=OWNER_NAME,
        user_id=user_handle,
        user_display_name="homelab-harness owner",
        challenge=challenge,
        timeout=TIMEOUT_MS,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=c) for c in existing],
    )
    return json.loads(options_to_json(options))


def verify_registration(
    *, credential: dict[str, Any], challenge: bytes, rp_id: str, origin: str
) -> NewPasskey:
    """Verify the browser's answer to :func:`registration_options`.

    Raises:
        PasskeyError: If the response does not verify.
    """
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError):
        raise PasskeyError("the passkey registration could not be verified") from None
    return NewPasskey(
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
    )


def authentication_options(
    *, rp_id: str, challenge: bytes, allowed: Sequence[bytes]
) -> dict[str, Any]:
    """Options for ``navigator.credentials.get()``, as JSON-ready data."""
    options = generate_authentication_options(
        rp_id=rp_id,
        challenge=challenge,
        timeout=TIMEOUT_MS,
        allow_credentials=[PublicKeyCredentialDescriptor(id=c) for c in allowed],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return json.loads(options_to_json(options))


def verify_authentication(
    *,
    credential: dict[str, Any],
    challenge: bytes,
    rp_id: str,
    origin: str,
    public_key: bytes,
    sign_count: int,
) -> int:
    """Verify an assertion and return the authenticator's new signature counter.

    Raises:
        PasskeyError: If it does not verify (including a counter that went
            backwards, which suggests a cloned authenticator).
    """
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=public_key,
            credential_current_sign_count=sign_count,
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError):
        raise PasskeyError("the passkey could not be verified") from None
    return verified.new_sign_count
