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
from opentelemetry import trace

from homelab_harness.redaction import Redactor, redactor
from homelab_harness.settings import LogFormat, Settings
from homelab_harness.telemetry import Telemetry
from homelab_harness.telemetry.logs import OtlpLogHandler


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


def add_trace_context(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Add ``trace_id`` and ``span_id`` when the event is logged inside a span.

    The IDs use the W3C hex form that Tempo and Grafana search by, so a log line
    in Loki links straight to its trace.
    """
    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        event_dict.setdefault("trace_id", format(ctx.trace_id, "032x"))
        event_dict.setdefault("span_id", format(ctx.span_id, "016x"))
    return event_dict


def _formatter(
    shared: list[structlog.types.Processor], renderer: structlog.types.Processor
) -> logging.Formatter:
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )


def configure_logging(settings: Settings, telemetry: Telemetry | None = None) -> None:
    """Configure structlog and route stdlib logging (uvicorn, libraries) through it.

    Args:
        settings: Process settings; uses ``log_level`` and ``log_format``.
        telemetry: When it has a logger provider, every record is also exported
            over OTLP, rendered as the same redacted JSON whatever ``log_format``
            says (Loki parses JSON; console colours are for terminals).
    """
    level = logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO)
    json_renderer = structlog.processors.JSONRenderer()
    renderer: structlog.types.Processor = (
        json_renderer
        if settings.log_format is LogFormat.JSON
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_trace_context,
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
    handler.setFormatter(_formatter(shared, renderer))
    handlers: list[logging.Handler] = [handler]
    if telemetry is not None and telemetry.logger_provider is not None:
        handlers.append(
            OtlpLogHandler(telemetry.logger_provider, _formatter(shared, json_renderer))
        )
    root = logging.getLogger()
    root.handlers[:] = handlers
    root.setLevel(level)
    # uvicorn installs its own handlers; let records propagate to ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
