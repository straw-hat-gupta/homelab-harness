"""Turning owner input into a kind's fields and metadata, and generating keys (pure logic).

The owner API accepts either one ``value`` (for kinds with a single secret field)
or a ``fields`` object, plus a ``metadata`` object. This module validates both
against the kind models in :mod:`homelab_harness.secrets.kinds` and derives the
metadata that must not be typed by hand (an SSH key's public key, a ``kv``'s key
names, a ``file``'s size).

Error messages name fields and rules, never the input.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from homelab_harness.secrets.kinds import (
    KIND_MODELS,
    FileFields,
    KvFields,
    KvMetadata,
    SecretFields,
    SecretKind,
    SecretMetadata,
    SecretValue,
    SshKeyFields,
)
from homelab_harness_sdk.errors import InvalidInput

PRIMARY_FIELD: Mapping[SecretKind, str] = {
    SecretKind.SSH_KEY: "private_key",
    SecretKind.PASSWORD: "password",
    SecretKind.API_TOKEN: "token",
    SecretKind.PROXMOX_TOKEN: "secret",
    SecretKind.CLOUDFLARE_TOKEN: "token",
    SecretKind.GITHUB_TOKEN: "token",
}
"""The field a single ``value`` fills, for every kind that has one."""

GENERATED_KINDS = frozenset({SecretKind.SSH_KEY})
"""Kinds the harness can generate in place."""

# OpenSSH "from=" patterns: hostnames, addresses, CIDRs, wildcards and negation.
_FROM_PATTERN = re.compile(r"^!?[A-Za-z0-9.:*?/_-]{1,255}$")
_FROM_MAX = 32
_COMMENT = re.compile(r"^[A-Za-z0-9 ._@:+-]{0,128}$")


def _problems(exc: ValidationError) -> str:
    # Pydantic's messages describe the rule (pattern, type, our fixed ValueErrors),
    # and the kind models hide input in errors; locations name the field.
    parts: list[str] = []
    for err in exc.errors(include_input=False, include_url=False):
        loc = ".".join(str(p) for p in err["loc"]) or "(object)"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(sorted(set(parts)))


def parse_fields(
    kind: SecretKind, *, value: str | None, fields: Mapping[str, Any] | None
) -> SecretFields:
    """Validate the secret part of an intake request.

    Args:
        kind: The secret's kind.
        value: The single secret value, for kinds listed in :data:`PRIMARY_FIELD`.
        fields: The kind's full fields object (``file`` content is base64).

    Returns:
        The kind's fields model, its values wrapped and registered with the redactor.

    Raises:
        InvalidInput: If neither or both inputs are given, the kind takes no
            single value, or the input fails the kind's rules.
    """
    if (value is None) == (fields is None):
        raise InvalidInput("give exactly one of 'value' and 'fields'")
    if fields is not None:
        raw: Mapping[str, Any] = fields
    else:
        primary = PRIMARY_FIELD.get(kind)
        if primary is None:
            raise InvalidInput(f"kind {kind} takes 'fields', not a single 'value'")
        raw = {primary: value}
    fields_model, _ = KIND_MODELS[kind]
    try:
        # JSON mode, so file content arrives as base64 like everywhere else.
        return fields_model.model_validate_json(json.dumps(dict(raw)))
    except ValidationError as exc:
        raise InvalidInput(f"{kind} fields are invalid: {_problems(exc)}") from None
    except (TypeError, ValueError):
        raise InvalidInput(f"{kind} fields must be a JSON object of strings") from None


def derive_metadata(
    kind: SecretKind, fields: SecretFields, metadata: Mapping[str, Any]
) -> SecretMetadata:
    """Validate the plain part, deriving what comes from the value itself.

    Args:
        kind: The secret's kind.
        fields: The validated fields (from :func:`parse_fields`).
        metadata: The owner's metadata input.

    Returns:
        The kind's metadata model. ``ssh_key`` takes only ``comment`` and derives
        the public key and fingerprint; ``kv`` derives its key names; ``file``
        derives its size.

    Raises:
        InvalidInput: If the metadata fails the kind's rules.
    """
    _, metadata_model = KIND_MODELS[kind]
    try:
        if isinstance(fields, SshKeyFields):
            extra = set(metadata) - {"comment"}
            if extra:
                raise InvalidInput("ssh_key metadata takes only 'comment'; the rest is derived")
            comment = str(metadata.get("comment", ""))
            if not _COMMENT.match(comment):
                raise InvalidInput("ssh_key comment must be up to 128 plain characters")
            return fields.public_metadata(comment=comment)
        if isinstance(fields, KvFields):
            if metadata:
                raise InvalidInput("kv metadata is derived from the key names; give none")
            return KvMetadata(keys=fields.key_names())
        if isinstance(fields, FileFields):
            return metadata_model.model_validate({**metadata, "size": len(fields.content)})
        return metadata_model.model_validate(dict(metadata))
    except ValidationError as exc:
        raise InvalidInput(f"{kind} metadata is invalid: {_problems(exc)}") from None
    except ValueError as exc:  # public_metadata: a key type with no OpenSSH form
        raise InvalidInput(f"{kind}: {exc}") from None


def carried_metadata(kind: SecretKind, stored: Mapping[str, Any]) -> dict[str, Any]:
    """Return the metadata input that keeps a secret's owner-typed metadata on rotation.

    Args:
        kind: The secret's kind.
        stored: Its current stored metadata.

    Returns:
        Input for :func:`derive_metadata` without the parts derived from the old
        value (public key and fingerprint, key names, size).
    """
    match kind:
        case SecretKind.SSH_KEY:
            return {"comment": stored.get("comment", "")}
        case SecretKind.KV:
            return {}
        case SecretKind.FILE:
            return {k: v for k, v in stored.items() if k != "size"}
        case _:
            return dict(stored)


def primary_value(kind: SecretKind, fields: SecretFields) -> SecretValue:
    """Return the single secret value of a one-value kind.

    Args:
        kind: The secret's kind.
        fields: Its decrypted fields.

    Returns:
        The wrapped value.

    Raises:
        InvalidInput: If the kind holds more than one value (``kv``, ``file``)
            or a key (``ssh_key``), which cannot stand in for a token.
    """
    if kind is SecretKind.SSH_KEY or kind not in PRIMARY_FIELD:
        raise InvalidInput(f"a {kind} secret cannot be used as a single token value")
    value = getattr(fields, PRIMARY_FIELD[kind])
    if not isinstance(value, SecretValue):  # pragma: no cover - the models guarantee it
        raise InvalidInput(f"a {kind} secret has no single value")
    return value


def generate_ssh_key() -> SshKeyFields:
    """Create a new ed25519 private key inside the harness.

    Returns:
        The fields of an ``ssh_key`` secret, private key in OpenSSH format,
        unencrypted (the vault's envelope encryption protects it at rest).
    """
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return SshKeyFields(private_key=SecretValue(pem))


def authorized_keys_line(public_key: str, *, from_hosts: Sequence[str] = ()) -> str:
    """Format an ``authorized_keys`` entry, optionally limited to source hosts.

    Args:
        public_key: The OpenSSH public key line (type, base64, optional comment).
        from_hosts: OpenSSH ``from=`` patterns (hosts, addresses, CIDRs).

    Returns:
        The line to append to ``~/.ssh/authorized_keys``.

    Raises:
        InvalidInput: If a pattern holds characters that could break the line.
    """
    check_from_hosts(from_hosts)
    if not from_hosts:
        return public_key
    return f'from="{",".join(from_hosts)}" {public_key}'


def check_from_hosts(from_hosts: Sequence[str]) -> None:
    """Refuse ``from=`` patterns that could break out of the ``authorized_keys`` option.

    Args:
        from_hosts: OpenSSH ``from=`` patterns.

    Raises:
        InvalidInput: If there are more than 32 or one holds other characters
            than a host, address, CIDR, wildcard or leading ``!``.
    """
    if len(from_hosts) > _FROM_MAX or not all(_FROM_PATTERN.match(h) for h in from_hosts):
        raise InvalidInput("from= patterns must be hosts, addresses or CIDRs (at most 32)")
