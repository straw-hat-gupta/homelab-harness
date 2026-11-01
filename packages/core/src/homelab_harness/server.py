"""Process entry point: ``homelab-harness`` runs the HTTP server."""

from __future__ import annotations

import structlog
import uvicorn

from homelab_harness.app import create_app
from homelab_harness.log_config import configure_logging
from homelab_harness.settings import get_settings
from homelab_harness.telemetry import configure_telemetry

log = structlog.get_logger(__name__)


def main() -> None:
    """Configure telemetry and logging, then serve the app with uvicorn."""
    settings = get_settings()
    telemetry = configure_telemetry(settings)
    configure_logging(settings, telemetry)
    if telemetry is None:
        log.info("telemetry_disabled", reason="HH_OTEL_EXPORTER_OTLP_ENDPOINT is not set")
    else:
        telemetry.activate()
        log.info("telemetry_enabled", signals=["traces", "metrics", "logs"])
    try:
        uvicorn.run(
            create_app(settings, telemetry),
            host=settings.host,
            port=settings.port,
            log_config=None,  # our handlers, our redaction
            proxy_headers=True,
            server_header=False,
        )
    finally:
        if telemetry is not None:
            telemetry.shutdown()


if __name__ == "__main__":  # pragma: no cover
    main()
