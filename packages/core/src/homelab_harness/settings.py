"""Process configuration, read once from the environment (R-24).

Every setting lives here with a safe default. Nothing else in the codebase reads
``os.environ`` for configuration, and no ``.env`` file is loaded implicitly, so a
stray file on a developer machine cannot change how tests or the server behave.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field
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


class Settings(BaseSettings):
    """All harness settings. Environment variables use the ``HH_`` prefix.

    Attributes:
        env: Deployment environment.
        host: Interface the HTTP server binds to.
        port: HTTP port.
        log_level: Minimum log level name.
        log_format: JSON or console rendering.
        service_name: Name reported in logs and telemetry.
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, read from the environment on first use."""
    return Settings()
