"""FastAPI application factory.

The interface layer: routes parse input, call one service, and shape the
response. Subsystems attach themselves here (routers, readiness checks) as they
are built.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from homelab_harness import __version__
from homelab_harness.health import CheckStatus, ReadinessRegistry
from homelab_harness.settings import Settings, get_settings

log = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the harness application.

    Args:
        settings: Settings to use; read from the environment when omitted.

    Returns:
        A configured FastAPI app. ``app.state.readiness`` holds the readiness
        registry for subsystems to register checks on.
    """
    settings = settings or get_settings()
    app = FastAPI(
        title="homelab-harness",
        version=__version__,
        docs_url="/docs" if settings.env != "prod" else None,
        redoc_url=None,
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
