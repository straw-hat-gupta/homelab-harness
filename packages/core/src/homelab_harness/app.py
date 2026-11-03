"""FastAPI application factory.

The interface layer: routes parse input, call one service, and shape the
response. Subsystems attach themselves here (routers, readiness checks) as they
are built.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.routing import Route

from homelab_harness import __version__
from homelab_harness.audit.service import AuditWriter
from homelab_harness.capabilities import discover_capabilities
from homelab_harness.db.engine import create_engine, create_session_factory
from homelab_harness.db.health import database_check
from homelab_harness.db.url import parse_database_url
from homelab_harness.health import CheckStatus, ReadinessRegistry
from homelab_harness.jobs.runtime import dbos_check, launch_dbos, shutdown_dbos
from homelab_harness.mcp.server import MCP_PATH, McpService, build_mcp
from homelab_harness.redaction import redactor
from homelab_harness.secrets.api import router as vault_router
from homelab_harness.secrets.keys import KeyProvider, build_key_provider, vault_check
from homelab_harness.secrets.service import VaultService
from homelab_harness.settings import Environment, Settings, get_settings
from homelab_harness.target_health import target_check
from homelab_harness.targets import TargetRegistry, TargetsFile, read_targets, resolve_vault_refs
from homelab_harness.telemetry import Telemetry
from homelab_harness.ui.api import router as ui_router
from homelab_harness.ui.service import UiReadService
from homelab_harness.ui.static import mount_ui
from homelab_harness_sdk.errors import InvalidInput

log = structlog.get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Run the MCP transport; open the database and launch DBOS when one is configured."""
    manager: StreamableHTTPSessionManager = app.state.mcp_manager
    # Database first: a startup error (a missing vault secret) then surfaces as
    # itself rather than inside the transport's task group, and on shutdown the
    # transport stops before the engine closes.
    async with _database_lifespan(app), manager.run():
        yield


@asynccontextmanager
async def _database_lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings: Settings = app.state.settings
    readiness: ReadinessRegistry = app.state.readiness
    if settings.database_url is None:
        if settings.env is not Environment.TEST:
            log.warning("database_not_configured", effect="no jobs, audit, vault or MCP clients")
        yield
        return
    engine = create_engine(settings)
    telemetry: Telemetry | None = app.state.telemetry
    if telemetry is not None:
        telemetry.instrument_engine(engine)
    sessions = create_session_factory(engine)
    app.state.db_sessions = sessions
    app.state.audit = AuditWriter(sessions)
    key_provider: KeyProvider | None = app.state.key_provider
    if key_provider is not None:
        app.state.vault = VaultService(sessions, keys=key_provider, audit=app.state.audit)
    readiness.register("database", database_check(engine))
    try:
        pending: TargetsFile | None = app.state.pending_targets
        if pending is not None:
            # Targets naming vault secrets wait for the database; a missing or
            # revoked secret stops startup like a broken secret file does.
            resolved = await resolve_vault_refs(pending.vault_refs(), vault=app.state.vault)
            _install_targets(app, pending.registry(resolved))
        launch_dbos(settings)
        readiness.register("dbos", dbos_check)
        yield
    finally:
        shutdown_dbos()
        await engine.dispose()


def create_app(settings: Settings | None = None, telemetry: Telemetry | None = None) -> FastAPI:
    """Build the harness application.

    Args:
        settings: Settings to use; read from the environment when omitted.
        telemetry: When given, every request is traced and measured, and the
            app engine's queries are traced. ``None`` leaves the app
            uninstrumented.

    Returns:
        A configured FastAPI app. ``app.state.readiness`` holds the readiness
        registry for subsystems to register checks on. With a database
        configured, startup also sets ``app.state.db_sessions`` (session
        factory) and ``app.state.audit`` (the audit writer). The MCP server is
        routed at ``/mcp``; it needs the database for client tokens and audit.
        ``app.state.key_provider`` is the vault's KEK provider, or ``None``
        when ``HH_SECRETS_KEK_PROVIDER`` is unset; with both a provider and a
        database, startup sets ``app.state.vault`` (the vault service) and the
        owner API under ``/api`` serves it. ``app.state.ui_service`` backs the
        UI's interim read façade under ``/api/ui``; with ``ui_dir`` set, the
        built UI is served at ``/``.

    Raises:
        InvalidInput: If ``database_url`` is set but is not a Postgres URL, the
            targets file is invalid, it names vault secrets while the vault
            is off, or ``ui_dir`` holds no build.
        KeyProviderError: If a KEK provider is configured but unusable (R-25).
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
    # Load KEKs now so a missing or broken provider stops startup (R-25).
    key_provider = build_key_provider(settings)
    app.state.key_provider = key_provider
    if key_provider is not None:
        app.state.readiness.register(
            "vault", vault_check(key_provider, store=lambda: getattr(app.state, "vault", None))
        )
    app.state.telemetry = telemetry
    if telemetry is not None:
        telemetry.instrument_app(app)
    _attach_mcp(app, settings)
    app.include_router(vault_router)
    app.state.ui_service = UiReadService(
        capabilities=app.state.capabilities,
        registry=lambda: app.state.mcp_service.registry,
        audit=lambda: getattr(app.state, "audit", None),
    )
    app.include_router(ui_router)
    app.add_exception_handler(RequestValidationError, _validation_error)

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

    if settings.ui_dir is not None:
        mount_ui(app, settings.ui_dir)  # last: its fallback route must not shadow any other
    return app


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    """422 without the rejected input: a request body can carry a secret value."""
    errors: Sequence[Mapping[str, Any]] = (
        exc.errors() if isinstance(exc, RequestValidationError) else ()
    )
    detail: list[dict[str, Any]] = [
        {"loc": list(e.get("loc", ())), "msg": str(e.get("msg", "")), "type": e.get("type", "")}
        for e in errors
    ]
    return JSONResponse({"detail": detail}, status_code=422)


def _attach_mcp(app: FastAPI, settings: Settings) -> None:
    """Discover capabilities, read targets, and route ``/mcp``.

    Targets whose credentials all come from secret files are installed now.
    When the file names vault secrets, they are installed at startup, after the
    database opens (see ``_database_lifespan``).
    """
    capabilities = discover_capabilities()
    app.state.capabilities = capabilities
    targets = (
        read_targets(settings.targets_file, capabilities)
        if settings.targets_file is not None
        else None
    )
    service = McpService(
        capabilities=capabilities,
        registry=TargetRegistry(),
        audit=lambda: getattr(app.state, "audit", None),
    )
    app.state.mcp_service = service
    app.state.pending_targets = None
    if targets is not None and targets.vault_refs():
        if settings.database_url is None or app.state.key_provider is None:
            raise InvalidInput(
                "the targets file names vault secrets (secret://...), which need "
                "HH_DATABASE_URL and HH_SECRETS_KEK_PROVIDER"
            )
        app.state.pending_targets = targets
    elif targets is not None:
        _install_targets(app, targets.registry())
    mcp_app, manager = build_mcp(service, sessions=lambda: getattr(app.state, "db_sessions", None))
    app.state.mcp_manager = manager
    app.router.routes.append(Route(MCP_PATH, endpoint=mcp_app, methods=["GET", "POST", "DELETE"]))


def _install_targets(app: FastAPI, registry: TargetRegistry) -> None:
    """Serve these targets over MCP and give each a readiness check."""
    readiness: ReadinessRegistry = app.state.readiness
    capabilities = app.state.capabilities
    for target in registry:
        readiness.register(
            f"{target.capability}:{target.name}",
            target_check(capabilities[target.capability], target),
        )
    service: McpService = app.state.mcp_service
    service.registry = registry
