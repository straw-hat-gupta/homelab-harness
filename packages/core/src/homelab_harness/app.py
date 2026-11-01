"""FastAPI application factory.

The interface layer: routes parse input, call one service, and shape the
response. Subsystems attach themselves here (routers, readiness checks) as they
are built.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from homelab_harness import __version__
from homelab_harness.audit.service import AuditWriter
from homelab_harness.db.engine import create_engine, create_session_factory
from homelab_harness.db.health import database_check
from homelab_harness.db.url import parse_database_url
from homelab_harness.health import CheckStatus, ReadinessRegistry
from homelab_harness.jobs.runtime import dbos_check, launch_dbos, shutdown_dbos
from homelab_harness.redaction import redactor
from homelab_harness.settings import Environment, Settings, get_settings

log = structlog.get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Open the database and launch DBOS when a database is configured."""
    settings: Settings = app.state.settings
    readiness: ReadinessRegistry = app.state.readiness
    if settings.database_url is None:
        if settings.env is not Environment.TEST:
            log.warning("database_not_configured", effect="no jobs, audit or vault")
        yield
        return
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    app.state.db_sessions = sessions
    app.state.audit = AuditWriter(sessions)
    readiness.register("database", database_check(engine))
    try:
        launch_dbos(settings)
        readiness.register("dbos", dbos_check)
        yield
    finally:
        shutdown_dbos()
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the harness application.

    Args:
        settings: Settings to use; read from the environment when omitted.

    Returns:
        A configured FastAPI app. ``app.state.readiness`` holds the readiness
        registry for subsystems to register checks on. With a database
        configured, startup also sets ``app.state.db_sessions`` (session
        factory) and ``app.state.audit`` (the audit writer).

    Raises:
        InvalidInput: If ``database_url`` is set but is not a Postgres URL.
    """
    settings = settings or get_settings()
    if settings.database_url is not None:
        # Mask the password everywhere before anything can log it.
        password = parse_database_url(settings.database_url.get_secret_value()).password
        if password:
            redactor.register(password)
    app = FastAPI(
        title="homelab-harness",
        version=__version__,
        docs_url="/docs" if settings.env != "prod" else None,
        redoc_url=None,
        lifespan=_lifespan,
    )
    app.state.settings = settings
    app.state.readiness = ReadinessRegistry()

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        """Liveness: the process is up and serving requests."""
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", tags=["health"])
    async def readyz(request: Request) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Readiness: aggregate of registered subsystem checks.

        Returns 503 only on ``fail``; ``degraded`` still serves (one target down
        should not take the harness out of rotation).
        """
        registry: ReadinessRegistry = request.app.state.readiness
        report = await registry.run()
        body: dict[str, Any] = {
            "status": report.status,
            "checks": {
                name: {"status": r.status, "detail": r.detail} for name, r in report.checks.items()
            },
        }
        code = 503 if report.status is CheckStatus.FAIL else 200
        if code != 200:
            log.warning(
                "readiness_failed",
                failing=[n for n, r in report.checks.items() if r.status is CheckStatus.FAIL],
            )
        return JSONResponse(body, status_code=code)

    return app
