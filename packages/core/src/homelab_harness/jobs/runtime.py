"""DBOS lifecycle: configure, launch and shut down the durable-workflow runtime.

DBOS keeps its system tables in the harness database under the ``dbos`` schema
and creates or migrates them itself at launch; Alembic manages only the app's
tables in ``public``. DBOS is a process-wide singleton, so one harness process
runs one DBOS instance.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import structlog
from dbos import DBOS, DBOSConfig

from homelab_harness.db.url import parse_database_url, render_database_url
from homelab_harness.health import CheckResult, CheckStatus
from homelab_harness.settings import Settings
from homelab_harness_sdk.errors import InvalidInput

log = structlog.get_logger(__name__)

SYSTEM_SCHEMA = "dbos"


def dbos_config(settings: Settings) -> DBOSConfig:
    """Build the DBOS configuration from settings.

    Args:
        settings: Process settings; ``database_url`` must be set.

    Returns:
        A config pointing DBOS at the harness database, with DBOS's own OTLP
        export off (the harness owns telemetry) and connection limits matching
        the app engine.

    Raises:
        InvalidInput: If no database URL is configured or it is not valid.
    """
    if settings.database_url is None:
        raise InvalidInput("HH_DATABASE_URL is not set")
    url = parse_database_url(settings.database_url.get_secret_value())
    return {
        "name": settings.service_name,
        "system_database_url": render_database_url(url),
        "dbos_system_schema": SYSTEM_SCHEMA,
        "sys_db_pool_size": settings.database_pool_size,
        "db_engine_kwargs": {
            "pool_timeout": settings.database_connect_timeout_seconds,
            "connect_args": {
                "application_name": f"{settings.service_name}-dbos",
                "connect_timeout": settings.database_connect_timeout_seconds,
            },
        },
        "log_level": settings.log_level.upper(),
        "enable_otlp": False,
    }


def _route_dbos_logs_through_harness() -> None:
    # Unless its logger already has a handler, DBOS installs a private console
    # handler and stops propagation, which would bypass redaction. A NullHandler
    # keeps DBOS from doing that, and records propagate to the root handler.
    dbos_logger = logging.getLogger("dbos")
    for handler in list(dbos_logger.handlers):
        dbos_logger.removeHandler(handler)
    dbos_logger.addHandler(logging.NullHandler())
    dbos_logger.propagate = True


def launch_dbos(settings: Settings) -> None:
    """Create and launch the DBOS runtime, recovering any pending workflows.

    Blocking: it connects to Postgres and migrates DBOS's schema. A database
    that is down at startup makes this raise, so the process fails fast and its
    supervisor restarts it.

    Args:
        settings: Process settings; ``database_url`` must be set.
    """
    _route_dbos_logs_through_harness()
    DBOS(config=dbos_config(settings))
    DBOS.launch()
    log.info("dbos_launched", schema=SYSTEM_SCHEMA)


def shutdown_dbos() -> None:
    """Stop DBOS, keeping registered workflows so a later launch can use them."""
    DBOS.destroy()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    # DBOS's async API installs its thread pool as the running loop's default
    # executor, and destroy() shuts that pool down. Without a fresh one, any
    # later run_in_executor on this loop (psycopg resolves hosts that way) fails.
    loop.set_default_executor(ThreadPoolExecutor(thread_name_prefix="asyncio"))


async def dbos_check() -> CheckResult:
    """Readiness: DBOS is launched and can query its system tables.

    DBOS exposes no health call, so this lists at most one workflow without
    loading inputs or outputs: a single indexed read on the system database.

    Returns:
        ``ok``, or ``fail`` with an owner-safe detail.
    """
    try:
        await DBOS.list_workflows_async(limit=1, load_input=False, load_output=False)
    except Exception as exc:  # DBOS not launched, or its database unreachable
        log.warning("dbos_check_failed", error_type=type(exc).__name__)
        return CheckResult(CheckStatus.FAIL, "unavailable")
    return CheckResult(CheckStatus.OK)
