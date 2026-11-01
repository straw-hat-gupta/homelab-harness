"""Key-encryption key (KEK) providers for the vault (secrets.md "KEK providers").

Every provider reads a *keyring*: one or more ``kek_id:base64key`` entries, newest
first. The first entry is the current KEK, used to wrap new DEKs; older entries stay
so records wrapped before a rotation still open until ``hh vault rotate-kek`` has
rewrapped them. Keys are loaded once, at construction, so a missing or broken
provider stops startup with a clear message (R-25). The KEK never goes to Postgres.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import os
import re
import secrets
import stat
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

import structlog

from homelab_harness.health import CheckFn, CheckResult, CheckStatus
from homelab_harness.secrets.crypto import KEY_BYTES, Kek, SecretIntegrityError, seal, unseal
from homelab_harness.settings import Environment, KekProviderKind, Settings

log = structlog.get_logger(__name__)

_ENTRY_SEPARATOR = re.compile(r"[\n,]")
_PROBE_ID = "readiness-probe"
_KEK_FILE_MODE = 0o400


class KeyProviderError(Exception):
    """The KEK source is missing, unreadable, insecure or malformed.

    Messages are owner-safe: they name files and line numbers, never key bytes.
    """


class KeyProvider(Protocol):
    """Source of KEKs: the current one, plus older ones looked up by id."""

    @property
    def name(self) -> str:
        """Provider name shown in readiness details (``file``, ``systemd-creds``, ``env``)."""
        ...

    def current(self) -> Kek:
        """Return the KEK that wraps new data keys."""
        ...

    def get(self, kek_id: str) -> Kek:
        """Return the KEK with this id.

        Raises:
            KeyProviderError: If no KEK has this id.
        """
        ...

    def kek_ids(self) -> tuple[str, ...]:
        """Return every known KEK id, newest first."""
        ...


def generate_kek(kek_id: str | None = None) -> Kek:
    """Create a new random 256-bit KEK.

    Args:
        kek_id: Identifier to give it; a random ``kek-<hex>`` id when omitted.

    Returns:
        The new key.
    """
    return Kek(kek_id=kek_id or f"kek-{secrets.token_hex(4)}", key=secrets.token_bytes(KEY_BYTES))


def keyring_line(kek: Kek) -> str:
    """Format a KEK as one keyring entry, ``kek_id:base64key``.

    Args:
        kek: The key to format.

    Returns:
        The entry, without a trailing newline.
    """
    return f"{kek.kek_id}:{base64.b64encode(kek.key).decode()}"


def parse_keyring(text: str, *, source: str) -> tuple[Kek, ...]:
    """Parse keyring entries separated by newlines or commas, newest first.

    Blank entries and lines starting with ``#`` are ignored.

    Args:
        text: The keyring text.
        source: Where it came from, used in error messages.

    Returns:
        The KEKs in file order (current first).

    Raises:
        KeyProviderError: If an entry is malformed, a key is not 32 bytes, an id
            repeats, or there are no entries.
    """
    keks: list[Kek] = []
    seen: set[str] = set()
    for number, raw in enumerate(_ENTRY_SEPARATOR.split(text), start=1):
        entry = raw.strip()
        if not entry or entry.startswith("#"):
            continue
        kek_id, sep, encoded = entry.partition(":")
        if not sep:
            raise KeyProviderError(f"{source}: entry {number} is not kek_id:base64key")
        try:
            key = base64.b64decode(encoded.strip(), validate=True)
        except (binascii.Error, ValueError):
            raise KeyProviderError(f"{source}: entry {number} is not valid base64") from None
        try:
            kek = Kek(kek_id=kek_id.strip(), key=key)
        except ValueError as exc:
            raise KeyProviderError(f"{source}: entry {number}: {exc}") from None
        if kek.kek_id in seen:
            raise KeyProviderError(f"{source}: KEK id {kek.kek_id!r} appears twice")
        seen.add(kek.kek_id)
        keks.append(kek)
    if not keks:
        raise KeyProviderError(f"{source}: no KEK entries")
    return tuple(keks)


class _Keyring:
    """Shared lookup over a parsed keyring."""

    def __init__(self, keks: Sequence[Kek], *, name: str) -> None:
        self._keks = tuple(keks)
        self._by_id = {k.kek_id: k for k in self._keks}
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def current(self) -> Kek:
        return self._keks[0]

    def get(self, kek_id: str) -> Kek:
        try:
            return self._by_id[kek_id]
        except KeyError:
            raise KeyProviderError(f"unknown KEK id {kek_id!r}") from None

    def kek_ids(self) -> tuple[str, ...]:
        return tuple(k.kek_id for k in self._keks)


def _read_private_file(path: Path) -> str:
    # Open first and fstat the descriptor, so the checked file is the one read.
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise KeyProviderError(f"KEK file {path} does not exist") from None
    except OSError as exc:
        raise KeyProviderError(f"KEK file {path} cannot be opened ({exc.strerror})") from None
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise KeyProviderError(f"KEK file {path} is not a regular file")
        mode = stat.S_IMODE(info.st_mode)
        # Owner read-only: the harness must not be able to rewrite its own KEK.
        if mode != _KEK_FILE_MODE:
            raise KeyProviderError(f"KEK file {path} has mode {mode:04o}; it must be 0400")
        if info.st_uid not in {os.geteuid(), 0}:
            raise KeyProviderError(
                f"KEK file {path} is owned by uid {info.st_uid}; "
                "it must be owned by the service user"
            )
        data = handle.read()
    try:
        return data.decode("ascii")
    except UnicodeDecodeError:
        raise KeyProviderError(f"KEK file {path} is not ASCII text") from None


class FileKeyProvider(_Keyring):
    """KEKs from a keyring file owned by the service user, mode 0400."""

    def __init__(self, path: Path) -> None:
        """Load and validate the key file.

        Args:
            path: The keyring file. Symlinks are refused.

        Raises:
            KeyProviderError: If the file is missing, a symlink, not mode 0400,
                owned by another user, or malformed.
        """
        super().__init__(parse_keyring(_read_private_file(path), source=str(path)), name="file")


class SystemdCredsKeyProvider(_Keyring):
    """KEKs from a systemd credential (``LoadCredentialEncrypted=``, TPM2-sealed if available).

    systemd decrypts the credential into ``$CREDENTIALS_DIRECTORY/<name>``, which
    only the service's user can read, so no mode check is made here.
    """

    def __init__(self, *, credentials_directory: Path | None, credential: str) -> None:
        """Load the keyring from the credential file.

        Args:
            credentials_directory: Value of ``$CREDENTIALS_DIRECTORY``.
            credential: Credential name, as given to ``LoadCredentialEncrypted=``.

        Raises:
            KeyProviderError: If systemd provided no credentials directory, or the
                credential is missing or malformed.
        """
        if credentials_directory is None:
            raise KeyProviderError(
                "systemd-creds provider selected but CREDENTIALS_DIRECTORY is not set"
            )
        if "/" in credential or credential in {"", ".", ".."}:
            raise KeyProviderError("credential name must be a plain file name")
        path = credentials_directory / credential
        try:
            text = path.read_text(encoding="ascii")
        except FileNotFoundError:
            raise KeyProviderError(f"systemd credential {credential!r} is not loaded") from None
        except (OSError, UnicodeDecodeError):
            raise KeyProviderError(f"systemd credential {credential!r} is unreadable") from None
        keks = parse_keyring(text, source=f"credential {credential}")
        super().__init__(keks, name="systemd-creds")


class EnvKeyProvider(_Keyring):
    """KEKs from ``HH_SECRETS_KEK``. For dev and test only; refused in prod."""

    def __init__(self, keyring: str, *, env: Environment) -> None:
        """Parse the keyring from the variable's value.

        Args:
            keyring: ``kek_id:base64key`` entries separated by commas or newlines.
            env: The deployment environment.

        Raises:
            KeyProviderError: In ``prod``, or if the value is malformed.
        """
        if env is Environment.PROD:
            raise KeyProviderError("the env KEK provider is for dev and test only, not prod")
        super().__init__(parse_keyring(keyring, source="HH_SECRETS_KEK"), name="env")


def build_key_provider(settings: Settings) -> KeyProvider | None:
    """Construct the configured KEK provider.

    Args:
        settings: Process settings.

    Returns:
        The provider, or ``None`` when ``HH_SECRETS_KEK_PROVIDER`` is unset.

    Raises:
        KeyProviderError: If the provider is misconfigured or its keys are unusable.
    """
    match settings.secrets_kek_provider:
        case None:
            return None
        case KekProviderKind.FILE:
            if settings.secrets_kek_file is None:
                raise KeyProviderError(
                    "file KEK provider selected but HH_SECRETS_KEK_FILE is unset"
                )
            return FileKeyProvider(settings.secrets_kek_file)
        case KekProviderKind.SYSTEMD_CREDS:
            return SystemdCredsKeyProvider(
                credentials_directory=settings.credentials_directory,
                credential=settings.secrets_kek_credential,
            )
        case KekProviderKind.ENV:
            if settings.secrets_kek is None:
                raise KeyProviderError("env KEK provider selected but HH_SECRETS_KEK is unset")
            return EnvKeyProvider(settings.secrets_kek.get_secret_value(), env=settings.env)


class VaultStore(Protocol):
    """The part of the vault service the readiness check probes."""

    async def versions_on_other_keks(self) -> int:
        """Count stored versions not yet wrapped by the current KEK."""
        ...


_STORE_TIMEOUT_SECONDS = 1.5  # below the registry's 2 s, so the check reports its own reason


def vault_check(
    provider: KeyProvider, *, store: Callable[[], VaultStore | None] | None = None
) -> CheckFn:
    """Build the ``vault`` readiness check for a provider.

    The check seals and opens a random probe with the current KEK. It reports
    *degraded* for the env provider, which must not hold real secrets. When the
    vault's tables are available (``store`` returns a service), it also counts
    the versions still wrapped by an older KEK, which proves the ``secrets``
    tables answer; a failing query fails the check.

    Args:
        provider: The configured KEK provider.
        store: Returns the vault service once the database is open, else ``None``.

    Returns:
        A coroutine function for :meth:`ReadinessRegistry.register`.
    """

    async def check() -> CheckResult:
        kek = provider.current()
        probe = secrets.token_bytes(16)
        try:
            sealed = seal(probe, secret_id=_PROBE_ID, version=1, kind="probe", kek=kek)
            ok = unseal(sealed, kek=kek) == probe
        except SecretIntegrityError:
            ok = False
        if not ok:
            return CheckResult(CheckStatus.FAIL, f"{provider.name} provider: KEK self-test failed")
        count = len(provider.kek_ids())
        detail = f"{provider.name} provider, current KEK {kek.kek_id}, {count} key(s)"
        vault = store() if store is not None else None
        if vault is not None:
            try:
                async with asyncio.timeout(_STORE_TIMEOUT_SECONDS):
                    stale = await vault.versions_on_other_keks()
            except Exception as exc:  # any driver failure means "not ready"
                log.warning("vault_check_store_failed", error_type=type(exc).__name__)
                return CheckResult(CheckStatus.FAIL, f"{detail}; secrets tables unreachable")
            if stale:
                detail += f"; {stale} version(s) on an older KEK (run hh vault rotate-kek)"
        if provider.name == "env":
            return CheckResult(
                CheckStatus.DEGRADED, f"{detail}; env KEKs are for dev and test only"
            )
        return CheckResult(CheckStatus.OK, detail)

    return check
