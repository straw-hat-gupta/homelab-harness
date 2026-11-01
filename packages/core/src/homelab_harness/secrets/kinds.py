"""Secret kinds: what each kind encrypts and what it keeps as plain metadata.

Each kind has two pydantic models (secrets.md "Secret kinds"):

* ``<Kind>Fields`` holds the values that are sealed. Secret values are wrapped in
  :class:`SecretValue` / :class:`SecretBytes`, which never show themselves through
  ``repr``, ``str``, formatting, ``model_dump`` or JSON; only ``.reveal()`` returns
  the value. Creating one registers the value with the process redactor, so a
  decrypted value is masked in logs from that moment on.
* ``<Kind>Metadata`` holds what may be shown to agents and the owner.

:func:`encode_fields` and :func:`decode_fields` convert fields to and from the
plaintext bytes that :mod:`homelab_harness.secrets.crypto` seals.

``totp_seed`` is not implemented yet (after v1).
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import hmac
import re
import uuid
from collections.abc import Callable
from enum import StrEnum
from typing import Any, ClassVar, Literal, Self, final

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from pydantic import (
    AnyHttpUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import core_schema

from homelab_harness.redaction import redactor
from homelab_harness.secrets.crypto import SecretIntegrityError

MASKED = "***"
MAX_FILE_BYTES = 1024 * 1024
"""Largest ``file`` secret accepted (kubeconfigs, certificates, ``.env`` files)."""

# Larger values are not registered with the redactor: one huge needle in its regex
# costs more than it protects, since leaks of big files are partial anyway.
_MAX_REGISTERED_BYTES = 64 * 1024

# Only this module may ask the serializers to reveal values (see encode_fields).
_REVEAL = object()


class SecretKind(StrEnum):
    """Secret kinds from secrets.md."""

    SSH_KEY = "ssh_key"
    PASSWORD = "password"  # noqa: S105 - a kind name
    API_TOKEN = "api_token"  # noqa: S105 - a kind name
    PROXMOX_TOKEN = "proxmox_token"  # noqa: S105 - a kind name
    CLOUDFLARE_TOKEN = "cloudflare_token"  # noqa: S105 - a kind name
    GITHUB_TOKEN = "github_token"  # noqa: S105 - a kind name
    FILE = "file"
    KV = "kv"


def _revealing(info: core_schema.SerializationInfo) -> bool:
    context: object = info.context
    return isinstance(context, dict) and _REVEAL in context


@final
class SecretValue:
    """A secret string that never reveals itself by accident.

    ``repr``, ``str`` and f-strings show ``SecretValue(***)``; pydantic dumps show
    ``***``. Pickling is refused. Equality is constant-time.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        """Wrap a value and register it with the redactor.

        Args:
            value: The plaintext secret.
        """
        self._value = value
        redactor.register(value)

    def reveal(self) -> str:
        """Return the plaintext. Keep the result in the narrowest scope possible."""
        return self._value

    def __repr__(self) -> str:
        """Return a fixed mask."""
        return "SecretValue(***)"

    __str__ = __repr__

    def __format__(self, format_spec: str) -> str:
        """Return the mask whatever the format spec."""
        return repr(self)

    def __eq__(self, other: object) -> bool:
        """Compare in constant time with another SecretValue."""
        if not isinstance(other, SecretValue):
            return NotImplemented
        return hmac.compare_digest(self._value.encode(), other._value.encode())

    __hash__ = None  # type: ignore[assignment]  # mutable-free but unhashable, like a secret should be

    def __reduce__(self) -> str:
        """Refuse pickling, which would write the value out."""
        raise TypeError("SecretValue cannot be pickled")

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: type[Any], handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        """Validate from ``str`` or ``SecretValue``; serialize masked unless revealing."""
        from_str = core_schema.no_info_after_validator_function(cls, core_schema.str_schema())
        return core_schema.json_or_python_schema(
            json_schema=from_str,
            python_schema=core_schema.union_schema([core_schema.is_instance_schema(cls), from_str]),
            serialization=core_schema.plain_serializer_function_ser_schema(
                _serialize_secret_value, info_arg=True
            ),
        )


def _serialize_secret_value(value: SecretValue, info: core_schema.SerializationInfo) -> str:
    return value.reveal() if _revealing(info) else MASKED


def _decode_b64(text: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("expected base64") from None


@final
class SecretBytes:
    """A secret byte string (``file`` contents), masked like :class:`SecretValue`.

    JSON encoding, used only inside the sealed payload, is base64.
    """

    __slots__ = ("_value",)

    def __init__(self, value: bytes) -> None:
        """Wrap bytes and, when they are modest-sized UTF-8 text, register them.

        Args:
            value: The plaintext bytes.
        """
        self._value = bytes(value)
        if len(self._value) <= _MAX_REGISTERED_BYTES:
            # Binary content cannot appear verbatim in text logs, so skip it.
            with contextlib.suppress(UnicodeDecodeError):
                redactor.register(self._value.decode("utf-8"))

    def reveal(self) -> bytes:
        """Return the plaintext bytes."""
        return self._value

    def __len__(self) -> int:
        """Size in bytes; the size of a file is plain metadata."""
        return len(self._value)

    def __repr__(self) -> str:
        """Return a fixed mask."""
        return "SecretBytes(***)"

    __str__ = __repr__

    def __format__(self, format_spec: str) -> str:
        """Return the mask whatever the format spec."""
        return repr(self)

    def __eq__(self, other: object) -> bool:
        """Compare in constant time with another SecretBytes."""
        if not isinstance(other, SecretBytes):
            return NotImplemented
        return hmac.compare_digest(self._value, other._value)

    __hash__ = None  # type: ignore[assignment]

    def __reduce__(self) -> str:
        """Refuse pickling, which would write the value out."""
        raise TypeError("SecretBytes cannot be pickled")

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: type[Any], handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        """Validate from ``bytes`` (or base64 in JSON); serialize masked unless revealing."""
        from_bytes = core_schema.no_info_after_validator_function(cls, core_schema.bytes_schema())
        from_b64: Callable[[str], SecretBytes] = lambda text: cls(_decode_b64(text))  # noqa: E731
        return core_schema.json_or_python_schema(
            json_schema=core_schema.no_info_after_validator_function(
                from_b64, core_schema.str_schema()
            ),
            python_schema=core_schema.union_schema(
                [core_schema.is_instance_schema(cls), from_bytes]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                _serialize_secret_bytes, info_arg=True
            ),
        )


def _serialize_secret_bytes(value: SecretBytes, info: core_schema.SerializationInfo) -> str:
    return base64.b64encode(value.reveal()).decode() if _revealing(info) else MASKED


class SecretFields(BaseModel):
    """Base for the encrypted part of a secret.

    ``hide_input_in_errors`` keeps raw values out of ``ValidationError`` text.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    kind: ClassVar[SecretKind]


class SecretMetadata(BaseModel):
    """Base for the plain, displayable part of a secret."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --- ssh_key ---------------------------------------------------------------

_SSH_FINGERPRINT = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")


def _load_private_key(pem: str, passphrase: str | None) -> PrivateKeyTypes:
    data = pem.encode()
    password = passphrase.encode() if passphrase else None
    loader = (
        serialization.load_ssh_private_key
        if b"BEGIN OPENSSH PRIVATE KEY" in data
        else serialization.load_pem_private_key
    )
    try:
        return loader(data, password)
    except (ValueError, TypeError):
        # cryptography's messages are generic, but keep ours fixed to be certain.
        raise ValueError("private key could not be loaded (format or passphrase)") from None
    except UnsupportedAlgorithm:
        # Includes passphrase-protected OpenSSH-format keys, which need bcrypt.
        raise ValueError("private key format or algorithm is not supported") from None


def ssh_fingerprint(public_key_line: str) -> str:
    """Compute the ``ssh-keygen -l`` style SHA256 fingerprint of a public key.

    Args:
        public_key_line: An OpenSSH public key, ``<type> <base64> [comment]``.

    Returns:
        ``SHA256:`` followed by unpadded base64 of the key blob's SHA-256.

    Raises:
        ValueError: If the line is not an OpenSSH public key.
    """
    parts = public_key_line.split()
    if len(parts) < 2:
        raise ValueError("not an OpenSSH public key")
    blob = _decode_b64(parts[1])
    digest = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    return f"SHA256:{digest}"


class SshKeyFields(SecretFields):
    """Encrypted part of an ``ssh_key``: an OpenSSH or PEM private key."""

    kind: ClassVar[SecretKind] = SecretKind.SSH_KEY
    private_key: SecretValue
    passphrase: SecretValue | None = None
    certificate: str | None = None

    @model_validator(mode="after")
    def _key_loads(self) -> Self:
        self._load()
        return self

    def _load(self) -> PrivateKeyTypes:
        return _load_private_key(
            self.private_key.reveal(), self.passphrase.reveal() if self.passphrase else None
        )

    def public_metadata(self, *, comment: str = "") -> SshKeyMetadata:
        """Derive the plain metadata (public key and fingerprint) from the private key.

        Args:
            comment: Comment to append to the public key line.

        Returns:
            The metadata to store next to the sealed key.

        Raises:
            ValueError: If the key type has no OpenSSH public form.
        """
        try:
            public = (
                self._load()
                .public_key()
                .public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
            )
        except ValueError:
            raise ValueError("key type has no OpenSSH public key form") from None
        line = public.decode()
        return SshKeyMetadata(
            public_key=f"{line} {comment}".strip(),
            fingerprint=ssh_fingerprint(line),
            comment=comment,
        )


class SshKeyMetadata(SecretMetadata):
    """Plain part of an ``ssh_key``."""

    public_key: str
    fingerprint: str = Field(pattern=_SSH_FINGERPRINT.pattern)
    comment: str = ""


# --- password ---------------------------------------------------------------


class PasswordFields(SecretFields):
    """Encrypted part of a ``password``."""

    kind: ClassVar[SecretKind] = SecretKind.PASSWORD
    password: SecretValue


class PasswordMetadata(SecretMetadata):
    """Plain part of a ``password``."""

    username: str | None = None
    target: str | None = Field(default=None, description="URL or host the password is for")
    notes: str = ""


# --- api_token --------------------------------------------------------------


def _check_no_userinfo(urls: list[AnyHttpUrl]) -> list[AnyHttpUrl]:
    if any(u.username or u.password for u in urls):
        raise ValueError("base URLs must not embed credentials")
    return urls


class TokenFields(SecretFields):
    """Encrypted part of the token kinds: a single opaque token."""

    kind: ClassVar[SecretKind] = SecretKind.API_TOKEN
    token: SecretValue


class ApiTokenMetadata(SecretMetadata):
    """Plain part of an ``api_token``."""

    scheme: Literal["bearer", "token", "header"] = "bearer"
    header_name: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]{1,64}$")
    allowed_base_urls: list[AnyHttpUrl] = Field(default_factory=list[AnyHttpUrl])
    expires_at: AwareDatetime | None = None

    _urls = field_validator("allowed_base_urls")(_check_no_userinfo)

    @model_validator(mode="after")
    def _header_name_matches_scheme(self) -> Self:
        if (self.scheme == "header") != (self.header_name is not None):
            raise ValueError("header_name is required for, and only for, scheme 'header'")
        return self


# --- proxmox_token ----------------------------------------------------------

_PROXMOX_TOKEN_ID = re.compile(r"^[^\s@!:]+@[A-Za-z0-9._-]+![A-Za-z][A-Za-z0-9._-]*$")


class ProxmoxTokenFields(SecretFields):
    """Encrypted part of a ``proxmox_token``: the token's secret UUID."""

    kind: ClassVar[SecretKind] = SecretKind.PROXMOX_TOKEN
    secret: SecretValue

    @field_validator("secret")
    @classmethod
    def _is_uuid(cls, value: SecretValue) -> SecretValue:
        try:
            uuid.UUID(value.reveal())
        except ValueError:
            raise ValueError("Proxmox token secret must be a UUID") from None
        return value


class ProxmoxTokenMetadata(SecretMetadata):
    """Plain part of a ``proxmox_token``."""

    token_id: str = Field(pattern=_PROXMOX_TOKEN_ID.pattern, description="user@realm!tokenid")
    cluster: str | None = None
    privilege_tier: str | None = None
    expires_at: AwareDatetime | None = None


# --- cloudflare_token / github_token ----------------------------------------


class CloudflareTokenFields(TokenFields):
    """Encrypted part of a ``cloudflare_token``."""

    kind: ClassVar[SecretKind] = SecretKind.CLOUDFLARE_TOKEN


class CloudflareTokenMetadata(SecretMetadata):
    """Plain part of a ``cloudflare_token``."""

    scope: str = Field(description="account or zone the token is limited to")
    expires_at: AwareDatetime | None = None


class GithubTokenFields(TokenFields):
    """Encrypted part of a ``github_token``."""

    kind: ClassVar[SecretKind] = SecretKind.GITHUB_TOKEN


class GithubTokenMetadata(SecretMetadata):
    """Plain part of a ``github_token``."""

    repos: list[str] = Field(default_factory=list[str])
    permissions: list[str] = Field(default_factory=list[str])
    expires_at: AwareDatetime | None = None


# --- file -------------------------------------------------------------------


class FileFields(SecretFields):
    """Encrypted part of a ``file``: its bytes, at most :data:`MAX_FILE_BYTES`."""

    kind: ClassVar[SecretKind] = SecretKind.FILE
    content: SecretBytes

    @field_validator("content")
    @classmethod
    def _size_limit(cls, value: SecretBytes) -> SecretBytes:
        if len(value) > MAX_FILE_BYTES:
            raise ValueError(f"file secrets are limited to {MAX_FILE_BYTES} bytes")
        return value


class FileMetadata(SecretMetadata):
    """Plain part of a ``file``."""

    filename: str = Field(pattern=r"^[^/\\\x00]{1,255}$")
    mime_type: str = "application/octet-stream"
    size: int = Field(ge=0, le=MAX_FILE_BYTES)


# --- kv ---------------------------------------------------------------------

_KV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,127}")


class KvFields(SecretFields):
    """Encrypted part of a ``kv``: a map of key names to secret values."""

    kind: ClassVar[SecretKind] = SecretKind.KV
    values: dict[str, SecretValue] = Field(min_length=1)

    @field_validator("values")
    @classmethod
    def _key_names(cls, values: dict[str, SecretValue]) -> dict[str, SecretValue]:
        if not all(_KV_KEY.fullmatch(k) for k in values):
            raise ValueError("kv keys must match [A-Za-z_][A-Za-z0-9_.-]*")
        return values

    def key_names(self) -> list[str]:
        """Return the key names, sorted; these are the kind's plain metadata."""
        return sorted(self.values)


class KvMetadata(SecretMetadata):
    """Plain part of a ``kv``."""

    keys: list[str]


# --- registry and payload codec ---------------------------------------------

KIND_MODELS: dict[SecretKind, tuple[type[SecretFields], type[SecretMetadata]]] = {
    SecretKind.SSH_KEY: (SshKeyFields, SshKeyMetadata),
    SecretKind.PASSWORD: (PasswordFields, PasswordMetadata),
    SecretKind.API_TOKEN: (TokenFields, ApiTokenMetadata),
    SecretKind.PROXMOX_TOKEN: (ProxmoxTokenFields, ProxmoxTokenMetadata),
    SecretKind.CLOUDFLARE_TOKEN: (CloudflareTokenFields, CloudflareTokenMetadata),
    SecretKind.GITHUB_TOKEN: (GithubTokenFields, GithubTokenMetadata),
    SecretKind.FILE: (FileFields, FileMetadata),
    SecretKind.KV: (KvFields, KvMetadata),
}
"""Fields and metadata model for every implemented kind."""


def encode_fields(fields: SecretFields) -> bytes:
    """Serialize fields, values revealed, into the plaintext that gets sealed.

    Args:
        fields: The encrypted part of a secret.

    Returns:
        Compact JSON bytes. Seal them immediately; do not log or keep them.
    """
    return fields.model_dump_json(context={_REVEAL: True}).encode()


def decode_fields(kind: SecretKind, plaintext: bytes) -> SecretFields:
    """Parse unsealed plaintext back into the kind's fields model.

    Every value is wrapped (and so registered with the redactor) as it is parsed.

    Args:
        kind: The record's kind (authenticated by the AAD).
        plaintext: Bytes returned by ``unseal``.

    Returns:
        The fields model for ``kind``.

    Raises:
        SecretIntegrityError: If the plaintext does not fit the kind's schema.
    """
    fields_model, _ = KIND_MODELS[kind]
    try:
        return fields_model.model_validate_json(plaintext)
    except ValidationError:
        raise SecretIntegrityError(f"decrypted payload does not match kind {kind}") from None
