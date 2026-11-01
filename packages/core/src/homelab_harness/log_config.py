"""Structured logging with redaction applied to every event.

Log events carry identifiers (plan_id, job_id, upid, client_id) and counts, never
payloads. The redaction processor runs last before rendering, so even a mistake in
a call site cannot write a registered secret to stdout.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from homelab_harness.redaction import Redactor, redactor
from homelab_harness.settings import LogFormat, Settings

QUIET_LIBRARY_LOGGERS = ("httpx", "httpcore", "httpx2")
"""Libraries whose request logs carry target content; held at WARNING."""


class _StdoutHandler(logging.Handler):
    """Write formatted records to whatever ``sys.stdout`` is at emit time.

    ``logging.StreamHandler`` binds the stream once at construction, which breaks
    when stdout is later redirected (test capture, some process supervisors).
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stdout.write(self.format(record) + "\n")
            sys.stdout.flush()
        except Exception:
            self.handleError(record)


def redaction_processor(
    target: Redactor = redactor,
) -> structlog.types.Processor:
    """Build a structlog processor that masks secrets in the whole event dict.

    Args:
        target: The redactor to apply; the process-wide one by default.

    Returns:
        A processor suitable for ``structlog.configure``.
    """

    def _process(
        _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        return {k: target.scrub(v, key=k) for k, v in event_dict.items()}

    return _process


def configure_logging(settings: Settings) -> None:
    """Configure structlog and route stdlib logging (uvicorn, libraries) through it.

    Args:
        settings: Process settings; uses ``log_level`` and ``log_format``.
    """
    level = logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO)
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_format is LogFormat.JSON
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.format_exc_info,
        redaction_processor(),
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    handler = _StdoutHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # httpx logs every request at INFO with its full URL and the response's reason
    # phrase. Proxmox puts its error text (target content, sometimes config values)
    # in the reason phrase, and query strings can carry identifiers we do not log.
    # Adapters log their own redacted request lines instead (R-16).
    for name in QUIET_LIBRARY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    # uvicorn installs its own handlers; let records propagate to ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
