"""Process configuration, read once from the environment (R-24).

Every setting lives here with a safe default. Nothing else in the codebase reads
``os.environ`` for configuration, and no ``.env`` file is loaded implicitly, so a
stray file on a developer machine cannot change how tests or the server behave.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})


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
        targets_file: TOML file listing targets per capability, with each
            credential's vault handle (``secret://<name>``) or secret file.
            Interim, until targets are registered through ``hh``. When unset,
            no targets are registered and capability tools report that.
        secrets_kek_provider: KEK source; the vault is disabled when unset.
        secrets_kek_file: Key file for the ``file`` provider.
        secrets_kek_credential: Credential name for the ``systemd-creds`` provider.
        secrets_kek: Keyring for the ``env`` provider (dev and test only).
        credentials_directory: ``$CREDENTIALS_DIRECTORY``, set by systemd (no prefix).
        otel_exporter_otlp_endpoint: Base URL of an OTLP/HTTP receiver, usually
            the collector (``http://otel-collector:4318``). Traces, metrics and
            logs go to ``/v1/traces``, ``/v1/metrics`` and ``/v1/logs`` under it.
            When unset or empty, telemetry is off: no providers, no exporters, no
            instrumentation.
        otel_export_timeout_seconds: Limit on one export request, so a slow
            collector cannot stall the export threads.
        otel_metric_export_interval_seconds: How often metrics are pushed.
        public_url: The harness's own base URL as clients reach it, for example
            ``https://harness.<tailnet>.ts.net``. It is the OAuth issuer, the
            passkey relying party and the origin of the MCP resource
            (``<public_url>/mcp``). Must be HTTPS unless the host is loopback.
            When unset, the owner login and OAuth endpoints are off and ``/mcp``
            accepts only legacy bearer tokens.
        mcp_legacy_tokens: Whether ``/mcp`` still accepts the interim
            ``homelab-harness-token`` bearer tokens. Default true for now; it
            will default to false once the OAuth clients are verified live.
        oauth_access_token_seconds: Lifetime of an OAuth access token.
        oauth_refresh_token_seconds: Lifetime of a refresh token (rotated on use).
        oauth_dcr_enabled: Accept Dynamic Client Registration at
            ``/oauth/register`` (the deprecated fallback to client ID metadata
            documents). Registered clients still need the owner's consent.
        owner_session_idle_seconds: An owner session ends after this long unused.
        owner_session_max_seconds: An owner session ends this long after login.
        ui_dir: The web UI's build directory (``ui/dist``), served at ``/``.
            When unset, no UI is served; the image sets it.
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
    targets_file: Path | None = None
    secrets_kek_provider: KekProviderKind | None = None
    secrets_kek_file: Path | None = None
    secrets_kek_credential: str = "hh-kek"
    secrets_kek: SecretStr | None = None
    # systemd sets this unprefixed variable for LoadCredential=/LoadCredentialEncrypted=.
    credentials_directory: Path | None = Field(
        default=None, validation_alias="CREDENTIALS_DIRECTORY"
    )
    otel_exporter_otlp_endpoint: HttpUrl | None = None
    otel_export_timeout_seconds: int = Field(default=5, ge=1, le=60)
    otel_metric_export_interval_seconds: int = Field(default=15, ge=1, le=3600)
    public_url: HttpUrl | None = None
    mcp_legacy_tokens: bool = True
    oauth_access_token_seconds: int = Field(default=900, ge=60, le=3600)
    oauth_refresh_token_seconds: int = Field(default=30 * 86400, ge=3600, le=90 * 86400)
    oauth_dcr_enabled: bool = True
    owner_session_idle_seconds: int = Field(default=900, ge=60, le=86400)
    owner_session_max_seconds: int = Field(default=12 * 3600, ge=300, le=7 * 86400)
    ui_dir: Path | None = None

    @field_validator(
        "otel_exporter_otlp_endpoint",
        "public_url",
        "targets_file",
        "secrets_kek_provider",
        "secrets_kek_file",
        "ui_dir",
        mode="before",
    )
    @classmethod
    def _empty_endpoint_is_unset(cls, value: object) -> object:
        # Compose passes an unset variable through as "", which must mean "off".
        return None if value == "" else value

    @field_validator("public_url")
    @classmethod
    def _public_url_is_an_origin(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is None:
            return None
        if value.path not in (None, "", "/") or value.query or value.fragment:
            raise ValueError("public_url must be an origin, without a path, query or fragment")
        if value.username or value.password:
            raise ValueError("public_url must not contain credentials")
        # OAuth 2.1 and WebAuthn both need a secure context: HTTPS, or loopback in dev.
        if value.scheme != "https" and value.host not in _LOOPBACK_HOSTS:
            raise ValueError("public_url must use https unless the host is loopback")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, read from the environment on first use."""
    return Settings()
