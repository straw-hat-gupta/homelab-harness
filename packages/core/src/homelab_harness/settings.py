"""Process configuration, read once from the environment (R-24).

Every setting lives here with a safe default. Nothing else in the codebase reads
``os.environ`` for configuration, and no ``.env`` file is loaded implicitly, so a
stray file on a developer machine cannot change how tests or the server behave.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Deployment environment; affects only defaults and warnings, never safety rules."""

    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class LogFormat(StrEnum):
    """Log rendering: JSON for machines (Loki), console for humans."""

    JSON = "json"
    CONSOLE = "console"


class KekProviderKind(StrEnum):
    """Where the vault's key-encryption keys come from (secrets.md)."""

    FILE = "file"
    SYSTEMD_CREDS = "systemd-creds"
    ENV = "env"


class Settings(BaseSettings):
    """All harness settings. Environment variables use the ``HH_`` prefix.

    Attributes:
        env: Deployment environment.
        host: Interface the HTTP server binds to.
        port: HTTP port.
        log_level: Minimum log level name.
        log_format: JSON or console rendering.
        service_name: Name reported in logs and telemetry.
        database_url: Postgres URL (``postgresql://user:password@host:5432/db``).
            Holds a password, so it is a ``SecretStr`` and is never logged. When
            unset, the harness runs without a database, DBOS or audit log.
        database_pool_size: Connections kept open by the app's engine. DBOS
            keeps its own pool of the same size for its system tables.
        database_connect_timeout_seconds: Limit on opening one connection.
        database_statement_timeout_ms: Server-side limit on any one statement,
            so a stuck query cannot hold a connection forever.
        secrets_kek_provider: KEK source; the vault is disabled when unset.
        secrets_kek_file: Key file for the ``file`` provider.
        secrets_kek_credential: Credential name for the ``systemd-creds`` provider.
        secrets_kek: Keyring for the ``env`` provider (dev and test only).
        credentials_directory: ``$CREDENTIALS_DIRECTORY``, set by systemd (no prefix).
    """

    model_config = SettingsConfigDict(
        env_prefix="HH_",
        env_file=None,
        extra="ignore",
        frozen=True,
    )

    env: Environment = Environment.PROD
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON
    service_name: str = "homelab-harness"
    database_url: SecretStr | None = None
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    database_statement_timeout_ms: int = Field(default=15_000, ge=100, le=600_000)
    secrets_kek_provider: KekProviderKind | None = None
    secrets_kek_file: Path | None = None
    secrets_kek_credential: str = "hh-kek"
    secrets_kek: SecretStr | None = None
    # systemd sets this unprefixed variable for LoadCredential=/LoadCredentialEncrypted=.
    credentials_directory: Path | None = Field(
        default=None, validation_alias="CREDENTIALS_DIRECTORY"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, read from the environment on first use."""
    return Settings()
