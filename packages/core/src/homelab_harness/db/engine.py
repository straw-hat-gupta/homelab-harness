"""Async engine and session factory for the app's tables."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from homelab_harness.db.url import parse_database_url
from homelab_harness.settings import Settings
from homelab_harness_sdk.errors import InvalidInput

# Pool size is a setting; the rest are fixed because they encode policy rather
# than capacity: fail fast when the pool is exhausted, and recycle connections
# before typical NAT or firewall idle timeouts drop them.
_MAX_OVERFLOW = 2
_POOL_RECYCLE_SECONDS = 1800


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the app's async engine from settings.

    Args:
        settings: Process settings; ``database_url`` must be set.

    Returns:
        An engine with explicit pool limits, pre-ping, a connect timeout and a
        server-side statement timeout on every connection.

    Raises:
        InvalidInput: If no database URL is configured or it is not valid.
    """
    if settings.database_url is None:
        raise InvalidInput("HH_DATABASE_URL is not set")
    url = parse_database_url(settings.database_url.get_secret_value())
    return create_async_engine(
        url,
        pool_size=settings.database_pool_size,
        max_overflow=_MAX_OVERFLOW,
        pool_timeout=settings.database_connect_timeout_seconds,
        pool_pre_ping=True,
        pool_recycle=_POOL_RECYCLE_SECONDS,
        connect_args={
            "connect_timeout": settings.database_connect_timeout_seconds,
            "application_name": settings.service_name,
            "options": f"-c statement_timeout={settings.database_statement_timeout_ms}",
        },
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the session factory services use.

    Args:
        engine: The app engine.

    Returns:
        A factory whose sessions keep loaded attributes after commit, so a
        service can return what it just wrote without another query.
    """
    return async_sessionmaker(engine, expire_on_commit=False)
