"""Envelope encryption for vault secrets (secrets.md "Storage and encryption").

Each secret version gets a fresh 256-bit data key (DEK). The value is sealed with
AES-256-GCM under the DEK, and the DEK is sealed (wrapped) with AES-256-GCM under
the key-encryption key (KEK). Both layers bind the record's identity through the
associated data, so a ciphertext or wrapped DEK copied onto another secret, version,
kind or KEK id fails to open instead of decrypting under the wrong label.

There is deliberately no plaintext fallback (R-25, v0 cross-check item 7): every
failure raises :class:`SecretIntegrityError`.

Pure logic: no I/O, no framework imports.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32
NONCE_BYTES = 12
_TAG_BYTES = 16
_WRAPPED_DEK_BYTES = KEY_BYTES + _TAG_BYTES

# Identifiers end up inside the "|"-joined AAD, so they must not contain "|"; the
# character sets below also keep them readable in logs and key files.
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_KIND = re.compile(r"[a-z][a-z0-9_]{0,63}")
_KEK_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

_VALUE_AAD_PREFIX = b"hh-secret-v1"
_DEK_AAD_PREFIX = b"hh-dek-v1"


class SecretIntegrityError(Exception):
    """A sealed secret failed to open: tampered, wrong KEK, or malformed.

    The message is owner-safe and never contains key material or plaintext.
    """


@dataclass(frozen=True, slots=True)
class Kek:
    """A key-encryption key and its stable identifier.

    Attributes:
        kek_id: Identifier recorded next to every DEK it wraps.
        key: 32 raw key bytes. Excluded from ``repr``.
    """

    kek_id: str
    key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        """Reject malformed ids and keys that are not exactly 256 bits.

        Raises:
            ValueError: If the id or the key length is invalid.
        """
        if not _KEK_ID.fullmatch(self.kek_id):
            raise ValueError("KEK id must be 1-64 characters of [A-Za-z0-9._-]")
        if len(self.key) != KEY_BYTES:
            raise ValueError(f"KEK must be exactly {KEY_BYTES} bytes")


@dataclass(frozen=True, slots=True)
class EncryptedSecret:
    """One sealed secret version, as it is stored. Contains no plaintext.

    Attributes:
        ciphertext: AES-GCM ciphertext of the value, tag included.
        nonce: 96-bit nonce used with the DEK.
        wrapped_dek: The DEK sealed under the KEK, tag included.
        dek_nonce: 96-bit nonce used with the KEK.
        kek_id: Which KEK wrapped the DEK.
        version: Secret version number (rotation creates a new one).
        kind: Secret kind, for example ``api_token``.
        secret_id: Stable identifier of the secret.
    """

    ciphertext: bytes = field(repr=False)
    nonce: bytes
    wrapped_dek: bytes = field(repr=False)
    dek_nonce: bytes
    kek_id: str
    version: int
    kind: str
    secret_id: str


def _check_identity(*, secret_id: str, version: int, kind: str) -> None:
    if not _ID.fullmatch(secret_id):
        raise ValueError("secret_id must be 1-128 characters of [A-Za-z0-9._:-]")
    if not _KIND.fullmatch(kind):
        raise ValueError("kind must be lower snake case")
    if version < 1:
        raise ValueError("version must be >= 1")


def _value_aad(*, secret_id: str, version: int, kind: str) -> bytes:
    return b"|".join((_VALUE_AAD_PREFIX, secret_id.encode(), str(version).encode(), kind.encode()))


def _dek_aad(*, kek_id: str, secret_id: str, version: int, kind: str) -> bytes:
    # The wrapped DEK is bound to the record too, so it cannot be moved to another row.
    return b"|".join(
        (_DEK_AAD_PREFIX, kek_id.encode(), secret_id.encode(), str(version).encode(), kind.encode())
    )


def seal(plaintext: bytes, *, secret_id: str, version: int, kind: str, kek: Kek) -> EncryptedSecret:
    """Encrypt one secret version under a fresh DEK wrapped by ``kek``.

    Args:
        plaintext: The serialized secret value.
        secret_id: Stable identifier of the secret.
        version: Version number, starting at 1.
        kind: Secret kind name.
        kek: The current key-encryption key.

    Returns:
        The sealed record.

    Raises:
        ValueError: If an identifier is malformed.
    """
    _check_identity(secret_id=secret_id, version=version, kind=kind)
    dek = AESGCM.generate_key(bit_length=KEY_BYTES * 8)
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(dek).encrypt(
        nonce, plaintext, _value_aad(secret_id=secret_id, version=version, kind=kind)
    )
    dek_nonce = os.urandom(NONCE_BYTES)
    wrapped_dek = AESGCM(kek.key).encrypt(
        dek_nonce,
        dek,
        _dek_aad(kek_id=kek.kek_id, secret_id=secret_id, version=version, kind=kind),
    )
    return EncryptedSecret(
        ciphertext=ciphertext,
        nonce=nonce,
        wrapped_dek=wrapped_dek,
        dek_nonce=dek_nonce,
        kek_id=kek.kek_id,
        version=version,
        kind=kind,
        secret_id=secret_id,
    )


def _unwrap_dek(encrypted: EncryptedSecret, kek: Kek) -> bytes:
    if kek.kek_id != encrypted.kek_id:
        raise SecretIntegrityError("secret was wrapped by a different KEK")
    if (
        len(encrypted.nonce) != NONCE_BYTES
        or len(encrypted.dek_nonce) != NONCE_BYTES
        or len(encrypted.wrapped_dek) != _WRAPPED_DEK_BYTES
        or len(encrypted.ciphertext) < _TAG_BYTES
    ):
        raise SecretIntegrityError("sealed secret is malformed")
    try:
        _check_identity(
            secret_id=encrypted.secret_id, version=encrypted.version, kind=encrypted.kind
        )
    except ValueError:
        raise SecretIntegrityError("sealed secret is malformed") from None
    aad = _dek_aad(
        kek_id=encrypted.kek_id,
        secret_id=encrypted.secret_id,
        version=encrypted.version,
        kind=encrypted.kind,
    )
    try:
        return AESGCM(kek.key).decrypt(encrypted.dek_nonce, encrypted.wrapped_dek, aad)
    except InvalidTag:
        raise SecretIntegrityError("data key failed authentication") from None


def unseal(encrypted: EncryptedSecret, *, kek: Kek) -> bytes:
    """Decrypt a sealed secret version.

    Args:
        encrypted: The stored record.
        kek: The KEK named by ``encrypted.kek_id``.

    Returns:
        The plaintext bytes. Callers wrap them in a ``SecretValue`` straight away.

    Raises:
        SecretIntegrityError: If the KEK does not match or any field was altered.
    """
    dek = _unwrap_dek(encrypted, kek)
    aad = _value_aad(secret_id=encrypted.secret_id, version=encrypted.version, kind=encrypted.kind)
    try:
        return AESGCM(dek).decrypt(encrypted.nonce, encrypted.ciphertext, aad)
    except InvalidTag:
        raise SecretIntegrityError("secret value failed authentication") from None


def rewrap(encrypted: EncryptedSecret, *, old_kek: Kek, new_kek: Kek) -> EncryptedSecret:
    """Re-wrap the DEK under a new KEK, leaving the value ciphertext untouched.

    This is KEK rotation (``hh vault rotate-kek``): only the 48-byte wrapped DEK
    changes, so the value is never decrypted.

    Args:
        encrypted: The stored record, wrapped by ``old_kek``.
        old_kek: The KEK that currently wraps the DEK.
        new_kek: The KEK to wrap it with from now on.

    Returns:
        A copy of the record with a new ``wrapped_dek``, ``dek_nonce`` and ``kek_id``.

    Raises:
        SecretIntegrityError: If the DEK does not open under ``old_kek``.
    """
    dek = _unwrap_dek(encrypted, old_kek)
    dek_nonce = os.urandom(NONCE_BYTES)
    wrapped_dek = AESGCM(new_kek.key).encrypt(
        dek_nonce,
        dek,
        _dek_aad(
            kek_id=new_kek.kek_id,
            secret_id=encrypted.secret_id,
            version=encrypted.version,
            kind=encrypted.kind,
        ),
    )
    return replace(encrypted, wrapped_dek=wrapped_dek, dek_nonce=dek_nonce, kek_id=new_kek.kek_id)
