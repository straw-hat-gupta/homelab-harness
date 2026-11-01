"""Ship the harness's own log events to the collector over OTLP.

Why OTLP from the process rather than tailing container logs: it needs no host
mounts, no root and no Docker socket in the collector, behaves the same on Linux
and Docker Desktop, and carries the active span's context natively, so Grafana
can jump from a log line to its trace. Stdout JSON stays as it is, so
``docker logs`` keeps working and nothing depends on the collector being up.

The OpenTelemetry Python logs API is still marked experimental (its modules are
underscored), so its use is confined to this module and ``providers.py``.
"""

from __future__ import annotations

import logging

from opentelemetry import context as otel_context
from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk._logs import LoggerProvider

_SEVERITY = {
    logging.DEBUG: SeverityNumber.DEBUG,
    logging.INFO: SeverityNumber.INFO,
    logging.WARNING: SeverityNumber.WARN,
    logging.ERROR: SeverityNumber.ERROR,
    logging.CRITICAL: SeverityNumber.FATAL,
}

# The exporters log their own failures. Shipping those over the pipeline that is
# failing would loop, so they stay on stdout only.
_OWN_LOGGERS = "opentelemetry"


def _severity(levelno: int) -> SeverityNumber:
    for threshold in (logging.CRITICAL, logging.ERROR, logging.WARNING, logging.INFO):
        if levelno >= threshold:
            return _SEVERITY[threshold]
    return SeverityNumber.DEBUG


class OtlpLogHandler(logging.Handler):
    """A logging handler that emits each record as one OTLP log record.

    The body is the record rendered by ``formatter``: the same redacted JSON line
    that goes to stdout. That keeps a single redaction path for both outputs, and
    keeps attributes we did not choose (the stdlib copies every ``extra``) out of
    the export.
    """

    def __init__(self, provider: LoggerProvider, formatter: logging.Formatter) -> None:
        """Create the handler.

        Args:
            provider: The SDK logger provider that batches and exports records.
            formatter: Renders a record to the redacted JSON line.
        """
        super().__init__()
        self._provider = provider
        self.setFormatter(formatter)

    def emit(self, record: logging.LogRecord) -> None:
        """Format the record and hand it to the provider's batch processor."""
        if record.name == _OWN_LOGGERS or record.name.startswith(_OWN_LOGGERS + "."):
            return
        try:
            self._provider.get_logger(record.name).emit(
                timestamp=int(record.created * 1e9),
                context=otel_context.get_current(),
                severity_number=_severity(record.levelno),
                severity_text=record.levelname,
                body=self.format(record),
            )
        except Exception:
            self.handleError(record)
