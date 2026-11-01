"""Registered targets and their credentials, from the targets file (interim).

Until targets are registered through ``hh``, they are listed in a TOML file
named by ``HH_TARGETS_FILE``. Each top-level key is a capability name holding an
array of target tables::

    [[proxmox]]
    name = "home"
    endpoints = ["pve1.lab.example:8006"]
    tls = { kind = "ca_bundle", path = "/etc/harness/pve-home-ca.pem" }
    [proxmox.credentials.read]
    token_id = "harness@pve!read"
    token_secret = "secret://pve-home-read"        # a vault secret, or
    # token_secret_file = "/run/secrets/pve-home-read"

Loading has two steps. :func:`read_targets` validates the file and reads each
secret file once (it must not be readable by group or others). Vault handles
are resolved afterwards by :func:`resolve_vault_refs`, once the database is
open, through :meth:`VaultService.resolve`, which audits each use. Every value
is registered with the redactor before anything else can see it. Error messages
name the entry and the field, never a value.
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
from homelab_harness.secrets.kinds import SecretKind
from homelab_harness.secrets.payloads import primary_value
from homelab_harness.secrets.service import VaultService
from homelab_harness_sdk import Conflict, Credential, InvalidInput, NotFound, TargetConfig

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


@dataclass(frozen=True, slots=True)
class VaultRef:
    """A credential the targets file takes from the vault (``token_secret = "secret://..."``).

    Attributes:
        capability: Capability name.
        target: Target name.
        tier: Credential tier.
        token_id: The credential's public identifier from the file.
        secret_name: The vault secret's name.
    """

    capability: str
    target: str
    tier: str
    token_id: str
    secret_name: str

    @property
    def where(self) -> str:
        """``capability/target/tier``, for messages and the audit consumer."""
        return f"{self.capability}/{self.target}/{self.tier}"


@dataclass(frozen=True, slots=True)
class _Entry:
    capability: str
    config: TargetConfig
    file_credentials: Mapping[str, Credential]
    vault_refs: tuple[VaultRef, ...]


class TargetsFile:
    """A validated targets file whose secret files have been read."""

    def __init__(self, entries: Sequence[_Entry]) -> None:
        """Keep the entries in file order.

        Args:
            entries: Validated entries.
        """
        self._entries = tuple(entries)

    def vault_refs(self) -> list[VaultRef]:
        """Every credential that names a vault secret, in file order."""
        return [ref for entry in self._entries for ref in entry.vault_refs]

    def registry(self, resolved: Mapping[VaultRef, str] | None = None) -> TargetRegistry:
        """Build the registry, filling vault credentials from ``resolved``.

        Args:
            resolved: Secret value per vault reference, from :func:`resolve_vault_refs`.

        Returns:
            The registry.

        Raises:
            InvalidInput: If a vault reference has no resolved value.
        """
        values = resolved or {}
        targets: list[Target] = []
        for entry in self._entries:
            credentials = dict(entry.file_credentials)
            for ref in entry.vault_refs:
                if ref not in values:
                    raise InvalidInput(f"targets file: {ref.where} is a vault secret not resolved")
                credentials[ref.tier] = Credential(
                    tier=ref.tier, token_id=ref.token_id, secret=values[ref]
                )
            targets.append(
                Target(
                    capability=entry.capability,
                    name=entry.config.name,
                    config=entry.config,
                    credentials=credentials,
                )
            )
        return TargetRegistry(targets)


def read_targets(
    path: Path,
    capabilities: Mapping[str, AnyCapability],
    *,
    scrubber: Redactor = redactor,
) -> TargetsFile:
    """Load and validate the targets file, reading every credential's secret file.

    Args:
        path: The TOML file.
        capabilities: Installed capabilities by name.
        scrubber: Redactor each secret is registered with.

    Returns:
        The validated file; vault references are still to be resolved.

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
    entries: list[_Entry] = []
    for capability_name, items in data.items():
        capability = capabilities.get(capability_name)
        if capability is None:
            raise InvalidInput(f"targets file names {capability_name!r}, which is not installed")
        if not isinstance(items, list):
            raise InvalidInput(f"targets file: '{capability_name}' must be an array of tables")
        seen: set[str] = set()
        for index, item in enumerate(cast(list[Any], items)):
            entry = _load_entry(capability, index, item, scrubber=scrubber)
            if entry.config.name in seen:
                raise InvalidInput(f"targets file: {capability_name} target names must be unique")
            seen.add(entry.config.name)
            entries.append(entry)
    return TargetsFile(entries)


def _load_entry(
    capability: AnyCapability, index: int, item: object, *, scrubber: Redactor
) -> _Entry:
    where = f"{capability.name}[{index}]"
    try:
        config: TargetConfig = capability.target_model.model_validate(item)
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in err["loc"]) or "(entry)" for err in exc.errors()})
        raise InvalidInput(f"targets file: {where} is invalid: {', '.join(fields)}") from None
    credentials: dict[str, Credential] = {}
    refs: list[VaultRef] = []
    for tier, ref in config.credentials.items():
        if tier not in capability.manifest.credential_tiers:
            raise InvalidInput(f"targets file: {where} names unknown credential tier {tier!r}")
        if ref.secret_name is not None:
            refs.append(
                VaultRef(
                    capability=capability.name,
                    target=config.name,
                    tier=tier,
                    token_id=ref.token_id,
                    secret_name=ref.secret_name,
                )
            )
        elif ref.token_secret_file is not None:
            secret = read_secret_file(ref.token_secret_file, label=f"{where}/{tier}")
            scrubber.register(secret)
            credentials[tier] = Credential(tier=tier, token_id=ref.token_id, secret=secret)
    return _Entry(
        capability=capability.name,
        config=config,
        file_credentials=credentials,
        vault_refs=tuple(refs),
    )


async def resolve_vault_refs(
    refs: Sequence[VaultRef], *, vault: VaultService, scrubber: Redactor = redactor
) -> dict[VaultRef, str]:
    """Resolve the targets file's vault references, once, at startup.

    Each use is audited as ``secret.used`` with consumer
    ``targets:<capability>/<target>/<tier>``. A ``proxmox_token`` secret's
    ``token_id`` must match the file's, so a handle cannot pair one token's
    secret with another token's id.

    Args:
        refs: References from :meth:`TargetsFile.vault_refs`.
        vault: The vault service.
        scrubber: Redactor each value is registered with.

    Returns:
        The value per reference.

    Raises:
        InvalidInput: If a secret is missing, revoked, of a kind with no single
            value, or its token id disagrees with the file.
    """
    values: dict[VaultRef, str] = {}
    for ref in refs:
        try:
            resolved = await vault.resolve(
                name=ref.secret_name,
                consumer=f"targets:{ref.where}",
                purpose="target-credential",
            )
        except NotFound:
            raise InvalidInput(
                f"targets file: {ref.where} names vault secret {ref.secret_name!r}, "
                "which does not exist"
            ) from None
        except Conflict as exc:
            raise InvalidInput(f"targets file: {ref.where}: {exc.safe_message}") from None
        if (
            resolved.kind is SecretKind.PROXMOX_TOKEN
            and resolved.metadata.get("token_id") != ref.token_id
        ):
            raise InvalidInput(
                f"targets file: {ref.where} token_id differs from the vault secret's token_id"
            )
        try:
            value = primary_value(resolved.kind, resolved.fields).reveal()
        except InvalidInput as exc:
            raise InvalidInput(f"targets file: {ref.where}: {exc.safe_message}") from None
        scrubber.register(value)
        values[ref] = value
    return values
