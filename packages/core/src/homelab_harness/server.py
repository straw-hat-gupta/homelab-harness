"""Process entry point: ``homelab-harness`` runs the HTTP server."""

from __future__ import annotations

import uvicorn

from homelab_harness.app import create_app
from homelab_harness.log_config import configure_logging
from homelab_harness.settings import get_settings


def main() -> None:
    """Configure logging and serve the app with uvicorn."""
    settings = get_settings()
    configure_logging(settings)
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,  # our handlers, our redaction
        proxy_headers=True,
        server_header=False,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
