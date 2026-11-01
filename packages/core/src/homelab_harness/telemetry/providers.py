"""OpenTelemetry providers, exporters and instrumentation for the harness.

Telemetry is off unless ``HH_OTEL_EXPORTER_OTLP_ENDPOINT`` is set: then there are
no providers, no exporter threads and no instrumentation, so nothing retries
against a collector that does not exist. When it is on, every span passes the
redacting processor before any exporter sees it.

Providers are built as plain objects and passed explicitly to each
instrumentation, so tests can build one with in-memory exporters. Only the
server process installs them as the OTel globals (:meth:`Telemetry.activate`),
which DBOS's workflow spans and future ``trace.get_tracer`` call sites use.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy.engine import (  # pyright: ignore[reportMissingTypeStubs]
    EngineTracer,
)
from opentelemetry.sdk._logs import LoggerProvider, LogRecordProcessor
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy.ext.asyncio import AsyncEngine

from homelab_harness import __version__
from homelab_harness.settings import Settings
from homelab_harness.telemetry.redaction import RedactingSpanProcessor

_SCOPE = "homelab_harness"
# The name the SQLAlchemy instrumentation's own global mode uses for this
# counter, so dashboards read the same series whichever way it is wired.
_DB_CONNECTIONS_USAGE = "db.client.connections.usage"


def build_resource(settings: Settings) -> Resource:
    """Describe this process to every backend.

    Built from settings only (not ``Resource.create``, which also reads
    ``OTEL_RESOURCE_ATTRIBUTES``), so configuration stays in one place (R-24).

    Args:
        settings: Process settings.

    Returns:
        A resource with ``service.name``, ``service.version`` and
        ``deployment.environment.name`` (the current semantic-convention name
        for ``deployment.environment``).
    """
    return Resource(
        {
            "service.name": settings.service_name,
            "service.version": __version__,
            "deployment.environment.name": settings.env.value,
        }
    )


@dataclass(slots=True)
class Telemetry:
    """The process's telemetry providers and what has been instrumented with them.

    Attributes:
        tracer_provider: Traces; every span is redacted before export.
        meter_provider: Metrics.
        logger_provider: Logs over OTLP, or ``None`` when log export is off.
    """

    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider | None = None
    _apps: list[FastAPI] = field(default_factory=list[FastAPI])
    _engines: list[EngineTracer] = field(default_factory=list[EngineTracer])
    _httpx: bool = False

    def instrument_app(self, app: FastAPI) -> None:
        """Trace and measure every HTTP request the app serves.

        Args:
            app: The FastAPI app, before it starts serving.
        """
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=self.tracer_provider,
            meter_provider=self.meter_provider,
            # One span per request; the per-message ASGI spans are noise here.
            exclude_spans=["receive", "send"],
        )
        self._apps.append(app)

    def instrument_engine(self, engine: AsyncEngine) -> None:
        """Trace the app engine's queries.

        Only this engine: the instrumentor's global mode would also wrap the
        engines DBOS creates and turn its background polling into a stream of
        root spans.

        Args:
            engine: The app's async engine.
        """
        meter = self.meter_provider.get_meter(_SCOPE)
        self._engines.append(
            EngineTracer(
                self.tracer_provider.get_tracer(_SCOPE, __version__),
                engine.sync_engine,
                meter.create_up_down_counter(
                    name=_DB_CONNECTIONS_USAGE,
                    unit="connections",
                    description="Connections in the app pool, by state.",
                ),
            )
        )

    def instrument_httpx(self) -> None:
        """Trace and measure outgoing httpx requests (adapters, the CLI client)."""
        HTTPXClientInstrumentor().instrument(
            tracer_provider=self.tracer_provider, meter_provider=self.meter_provider
        )
        self._httpx = True

    def activate(self) -> None:
        """Install these providers as the process globals and instrument httpx.

        Call once, from the server entry point. OTel refuses to replace a
        global provider, so tests use the providers directly instead.
        """
        trace.set_tracer_provider(self.tracer_provider)
        metrics.set_meter_provider(self.meter_provider)
        if self.logger_provider is not None:
            set_logger_provider(self.logger_provider)
        self.instrument_httpx()

    def shutdown(self) -> None:
        """Remove instrumentation, then flush and stop every exporter."""
        for app in self._apps:
            FastAPIInstrumentor.uninstrument_app(app)
        self._apps.clear()
        if self._engines:
            EngineTracer.remove_all_event_listeners()
            self._engines.clear()
        if self._httpx:
            HTTPXClientInstrumentor().uninstrument()
            self._httpx = False
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()
        if self.logger_provider is not None:
            self.logger_provider.shutdown()


def build_telemetry(
    settings: Settings,
    *,
    span_processor: SpanProcessor,
    metric_reader: MetricReader,
    log_processor: LogRecordProcessor | None = None,
) -> Telemetry:
    """Assemble providers around the given processors.

    Args:
        settings: Process settings, for the resource.
        span_processor: The exporting span processor; it is wrapped so it only
            receives redacted spans.
        metric_reader: Collects and exports metrics.
        log_processor: Exports log records; ``None`` disables log export.

    Returns:
        The telemetry handle. Nothing is instrumented yet.
    """
    resource = build_resource(settings)
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(RedactingSpanProcessor(span_processor))
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    logger_provider = None
    if log_processor is not None:
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(log_processor)
    return Telemetry(tracer_provider, meter_provider, logger_provider)


def configure_telemetry(settings: Settings) -> Telemetry | None:
    """Build OTLP/HTTP telemetry from settings, or nothing when it is not configured.

    Args:
        settings: Process settings; uses ``otel_exporter_otlp_endpoint``,
            ``otel_export_timeout_seconds`` and
            ``otel_metric_export_interval_seconds``.

    Returns:
        A telemetry handle exporting traces, metrics and logs to the endpoint,
        or ``None`` when no endpoint is set.
    """
    if settings.otel_exporter_otlp_endpoint is None:
        return None
    base = str(settings.otel_exporter_otlp_endpoint).rstrip("/")
    timeout = settings.otel_export_timeout_seconds
    return build_telemetry(
        settings,
        span_processor=BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{base}/v1/traces", timeout=timeout)
        ),
        metric_reader=PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=f"{base}/v1/metrics", timeout=timeout),
            export_interval_millis=settings.otel_metric_export_interval_seconds * 1000,
            export_timeout_millis=timeout * 1000,
        ),
        log_processor=BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=f"{base}/v1/logs", timeout=timeout)
        ),
    )
