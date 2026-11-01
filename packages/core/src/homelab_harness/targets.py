"""Registered targets and their credentials, from the targets file (interim).

Until the vault persists credentials (docs/spec/secrets.md), targets are listed
in a TOML file named by ``HH_TARGETS_FILE``. Each top-level key is a capability
name holding an array of target tables::

    [[proxmox]]
    name = "home"
    endpoints = ["pve1.lab.example:8006"]
    tls = { kind = "ca_bundle", path = "/etc/harness/pve-home-ca.pem" }
    [proxmox.credentials.read]
    token_id = "harness@pve!read"
    token_secret_file = "/run/secrets/pve-home-read"

Each secret file holds only the secret, must not be readable by group or
others, and is read once at startup. Its value is registered with the redactor
before anything else can see it. Error messages name the entry and the field,
never a value.
"""

from __future__ import annotations

import stat
import tomllib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from homelab_harness.capabilities import AnyCapability
from homelab_harness.redaction import Redactor, redactor
from homelab_harness_sdk import Credential, InvalidInput, TargetConfig

_MAX_SECRET_BYTES = 4096


@dataclass(frozen=True, slots=True)
class Target:
    """One registered target with its resolved credentials.

    Attributes:
        capability: Capability name, for example ``proxmox``.
        name: The owner's label for the target.
        config: The validated entry (the capability's ``target_model``).
        credentials: Credential per tier.
    """

    capability: str
    name: str
    config: TargetConfig
    credentials: Mapping[str, Credential]


class TargetRegistry:
    """Targets by capability and name, in file order."""

    def __init__(self, targets: Sequence[Target] = ()) -> None:
        """Index the targets.

        Args:
            targets: Loaded targets; names are unique per capability.
        """
        self._targets = tuple(targets)

    def __iter__(self) -> Iterator[Target]:
        """Iterate over every target."""
        return iter(self._targets)

    def names(self, capability: str) -> list[str]:
        """Names of a capability's targets, in file order."""
        return [t.name for t in self._targets if t.capability == capability]

    def get(self, capability: str, name: str | None) -> Target:
        """Find one target.

        Args:
            capability: Capability name.
            name: Target name; ``None`` selects the only target.

        Returns:
            The target.

        Raises:
            InvalidInput: If no target matches, or ``None`` is ambiguous.
        """
        candidates = [t for t in self._targets if t.capability == capability]
        if name is None:
            if len(candidates) == 1:
                return candidates[0]
            if not candidates:
                raise InvalidInput(f"no {capability} target is registered (see HH_TARGETS_FILE)")
            names = ", ".join(t.name for t in candidates)
            raise InvalidInput(f"several {capability} targets are registered; choose one: {names}")
        for target in candidates:
            if target.name == name:
                return target
        raise InvalidInput(f"unknown {capability} target; registered: {self._listing(candidates)}")

    @staticmethod
    def _listing(candidates: Sequence[Target]) -> str:
        return ", ".join(t.name for t in candidates) or "none"


def read_secret_file(path: Path, *, label: str) -> str:
    """Read one secret file, refusing loose permissions.

    Args:
        path: The file.
        label: ``capability/target/tier``, for messages.

    Returns:
        The secret, without surrounding whitespace.

    Raises:
        InvalidInput: If the file is missing, not a regular file, readable by
            group or others, empty, or too large.
    """
    try:
        info = path.stat()
    except OSError:
        raise InvalidInput(f"secret file for {label} cannot be read") from None
    if not stat.S_ISREG(info.st_mode):
        raise InvalidInput(f"secret file for {label} is not a regular file")
    if info.st_mode & 0o077:
        raise InvalidInput(f"secret file for {label} must not be accessible to group or others")
    if info.st_size > _MAX_SECRET_BYTES:
        raise InvalidInput(f"secret file for {label} is too large")
    try:
        secret = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        raise InvalidInput(f"secret file for {label} cannot be read") from None
    if not secret:
        raise InvalidInput(f"secret file for {label} is empty")
    return secret


def load_targets(
    path: Path,
    capabilities: Mapping[str, AnyCapability],
    *,
    scrubber: Redactor = redactor,
) -> TargetRegistry:
    """Load and validate the targets file, reading every credential's secret.

    Args:
        path: The TOML file.
        capabilities: Installed capabilities by name.
        scrubber: Redactor each secret is registered with.

    Returns:
        The registry.

    Raises:
        InvalidInput: If the file or any entry is invalid. The message names the
            entry and the failing fields, never their values.
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise InvalidInput("HH_TARGETS_FILE cannot be read") from None
    except tomllib.TOMLDecodeError:
        # The decode error can quote the offending text, which may hold a value.
        raise InvalidInput("HH_TARGETS_FILE is not valid TOML") from None
    targets: list[Target] = []
    for capability_name, entries in data.items():
        capability = capabilities.get(capability_name)
        if capability is None:
            raise InvalidInput(f"targets file names {capability_name!r}, which is not installed")
        if not isinstance(entries, list):
            raise InvalidInput(f"targets file: '{capability_name}' must be an array of tables")
        seen: set[str] = set()
        for index, entry in enumerate(cast(list[Any], entries)):
            target = _load_entry(capability, index, entry, scrubber=scrubber)
            if target.name in seen:
                raise InvalidInput(f"targets file: {capability_name} target names must be unique")
            seen.add(target.name)
            targets.append(target)
    return TargetRegistry(targets)


def _load_entry(
    capability: AnyCapability, index: int, entry: object, *, scrubber: Redactor
) -> Target:
    where = f"{capability.name}[{index}]"
    try:
        config: TargetConfig = capability.target_model.model_validate(entry)
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in err["loc"]) or "(entry)" for err in exc.errors()})
        raise InvalidInput(f"targets file: {where} is invalid: {', '.join(fields)}") from None
    credentials: dict[str, Credential] = {}
    for tier, ref in config.credentials.items():
        if tier not in capability.manifest.credential_tiers:
            raise InvalidInput(f"targets file: {where} names unknown credential tier {tier!r}")
        secret = read_secret_file(ref.token_secret_file, label=f"{where}/{tier}")
        scrubber.register(secret)
        credentials[tier] = Credential(tier=tier, token_id=ref.token_id, secret=secret)
    return Target(
        capability=capability.name, name=config.name, config=config, credentials=credentials
    )
