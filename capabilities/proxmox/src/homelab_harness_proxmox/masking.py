"""Masking of secret-bearing guest config keys before a config leaves the harness (§9).

Applied by ``proxmox.guest.get`` to the raw config from the API. Masking is by
key, so it holds whatever the value is:

* ``sshkeys`` is replaced by the keys' SHA-256 fingerprints (key comments are
  dropped: they are free text and often an e-mail address);
* ``args``, ``hookscript`` and ``cicustom`` can carry commands, paths and
  snippet contents, so their values are masked;
* any key matching ``pass``, ``secret``, ``token`` or ``key`` (``cipassword``
  included) is masked. This over-masks a few harmless keys (``keyboard``); that
  is the safe direction.

Pure logic: no I/O, no framework imports.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

MASK = "[MASKED]"

_SENSITIVE_KEY = re.compile(r"pass|secret|token|key", re.IGNORECASE)
_CONTENT_KEYS = frozenset({"args", "hookscript", "cicustom"})
_SSH_KEYS = "sshkeys"
# Fields shown separately (name, tags, description) or carried as metadata (digest).
_SHOWN_ELSEWHERE = frozenset({"name", "hostname", "tags", "description", "digest"})

type ConfigValue = str | int | float | bool


@dataclass(frozen=True, slots=True)
class MaskedConfig:
    """A guest config safe to return.

    Attributes:
        values: Config keys and values, with sensitive values replaced by :data:`MASK`.
        masked_keys: Keys whose values were masked, sorted.
        ssh_key_fingerprints: ``SHA256:…`` fingerprints of the configured SSH keys.
    """

    values: dict[str, ConfigValue]
    masked_keys: list[str]
    ssh_key_fingerprints: list[str]


def ssh_key_fingerprints(encoded: str) -> list[str]:
    """Fingerprint the public keys in a PVE ``sshkeys`` value.

    PVE stores the ``authorized_keys`` text URL-encoded. Each line is
    ``[options] type base64-blob [comment]``; the fingerprint is OpenSSH's
    ``SHA256:`` form of the blob. Lines without a decodable blob are skipped.

    Args:
        encoded: The raw ``sshkeys`` config value.

    Returns:
        One fingerprint per key, in file order.
    """
    fingerprints: list[str] = []
    for line in unquote(encoded).splitlines():
        for part in line.split():
            if len(part) < 32:
                continue
            try:
                blob = base64.b64decode(part, validate=True)
            except (binascii.Error, ValueError):
                continue
            digest = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
            fingerprints.append(f"SHA256:{digest}")
            break
    return fingerprints


def mask_guest_config(raw: Mapping[str, Any]) -> MaskedConfig:
    """Return a guest config with every secret-bearing value masked.

    Args:
        raw: The config ``data`` object as the API returned it.

    Returns:
        The masked config. Keys shown elsewhere in the tool result (name, tags,
        description, digest) are left out; nested values are not expected and
        are rendered as strings.
    """
    values: dict[str, ConfigValue] = {}
    masked: list[str] = []
    fingerprints: list[str] = []
    for key, value in raw.items():
        if key in _SHOWN_ELSEWHERE:
            continue
        if key == _SSH_KEYS:
            fingerprints = ssh_key_fingerprints(str(value))
            values[key] = MASK
            masked.append(key)
        elif key in _CONTENT_KEYS or _SENSITIVE_KEY.search(key):
            values[key] = MASK
            masked.append(key)
        elif isinstance(value, str | int | float | bool):
            values[key] = value
        else:
            values[key] = str(value)
    return MaskedConfig(
        values=values, masked_keys=sorted(masked), ssh_key_fingerprints=fingerprints
    )
