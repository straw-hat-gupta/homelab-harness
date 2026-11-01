import json
import logging
import re
from pathlib import Path

import httpx
import pytest
import respx
import structlog
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import SecretStr
from sqlalchemy import text

from homelab_harness import __version__
from homelab_harness.app import create_app
from homelab_harness.db.engine import create_engine
from homelab_harness.log_config import configure_logging
from homelab_harness.redaction import MASK, redactor
from homelab_harness.settings import Environment, LogFormat, Settings
from homelab_harness.telemetry import build_telemetry, configure_telemetry
from homelab_harness.telemetry import metrics as metric_names
from homelab_harness.telemetry.providers import build_resource

# Not a real credential: a marker that must never reach an exporter.
CANARY = "CANARY_telemetry_5c1e"
SPEC = Path(__file__).parents[3] / "docs" / "spec" / "observability.md"


@pytest.fixture
def settings():
    return Settings(env=Environment.TEST)


@pytest.fixture
def spans():
    return InMemorySpanExporter()


@pytest.fixture
def metric_reader():
    return InMemoryMetricReader()


@pytest.fixture
def log_records():
    return InMemoryLogRecordExporter()


@pytest.fixture
def telemetry(settings, spans, metric_reader, log_records):
    redactor.register(CANARY)
    t = build_telemetry(
        settings,
        span_processor=SimpleSpanProcessor(spans),
        metric_reader=metric_reader,
        log_processor=SimpleLogRecordProcessor(log_records),
    )
    yield t
    t.shutdown()
    redactor.clear()


@pytest.fixture
async def client(settings, telemetry):
    app = create_app(settings, telemetry)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def json_logging(settings, telemetry):
    configure_logging(settings.model_copy(update={"log_format": LogFormat.JSON}), telemetry)
    yield
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


def _exported_text(spans):
    return "\n".join(s.to_json() for s in spans.get_finished_spans())


def _metric_names(reader):
    data = reader.get_metrics_data()
    return {m.name for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics}


def test_telemetry_is_off_when_no_endpoint_is_set(settings):
    assert configure_telemetry(settings) is None
    assert create_app(settings).state.telemetry is None


def test_an_endpoint_turns_on_all_three_signals():
    # Port 9 (discard) on loopback: nothing listens, so any export fails fast.
    t = configure_telemetry(
        Settings(
            env=Environment.TEST,
            otel_exporter_otlp_endpoint="http://127.0.0.1:9/",
            otel_export_timeout_seconds=1,
        )
    )
    assert t is not None
    assert t.logger_provider is not None
    t.shutdown()


def test_resource_names_the_service_version_and_environment(settings):
    attrs = build_resource(settings).attributes
    assert attrs["service.name"] == "homelab-harness"
    assert attrs["service.version"] == __version__
    assert attrs["deployment.environment.name"] == "test"


async def test_a_request_produces_a_server_span_and_http_metrics(client, spans, metric_reader):
    r = await client.get("/healthz")
    assert r.status_code == 200
    server = [s for s in spans.get_finished_spans() if s.kind is SpanKind.SERVER]
    assert len(server) == 1
    assert server[0].name == "GET /healthz"
    assert server[0].attributes["http.route"] == "/healthz"
    assert any(n.startswith("http.server.") for n in _metric_names(metric_reader))


async def test_secrets_in_request_urls_are_masked_in_spans(client, spans):
    await client.get(f"/healthz?ticket={CANARY}&note={CANARY}")
    exported = _exported_text(spans)
    assert spans.get_finished_spans()
    assert CANARY not in exported


def test_span_processor_masks_canary_in_every_field(telemetry, spans):
    tracer = telemetry.tracer_provider.get_tracer("test")
    with tracer.start_as_current_span(f"call {CANARY}") as span:
        span.set_attribute("url.full", f"https://pve.example/api2/json?x={CANARY}")
        span.set_attribute("authorization", "PVEAPIToken=placeholder")
        span.set_attribute("harness.ids", [CANARY, "plan-1"])
        span.add_event("retry", {"detail": f"after {CANARY}"})
        span.record_exception(RuntimeError(f"rejected {CANARY}"))
        span.set_status(StatusCode.ERROR, f"failed with {CANARY}")
    (finished,) = spans.get_finished_spans()
    assert CANARY not in finished.to_json()
    assert finished.attributes["authorization"] == MASK
    assert list(finished.attributes["harness.ids"]) == [MASK, "plan-1"]
    assert finished.status.status_code is StatusCode.ERROR
    assert finished.status.description == f"failed with {MASK}"


async def test_outgoing_httpx_calls_are_traced_and_masked(telemetry, spans):
    telemetry.instrument_httpx()
    with respx.mock:
        respx.get("https://pve.example/api2/json/version").respond(200, json={"ok": True})
        async with httpx.AsyncClient() as http:
            r = await http.get(f"https://pve.example/api2/json/version?ticket={CANARY}")
    assert r.status_code == 200
    client_spans = [s for s in spans.get_finished_spans() if s.kind is SpanKind.CLIENT]
    assert len(client_spans) == 1
    assert CANARY not in client_spans[0].to_json()


def test_log_events_carry_the_active_trace_and_span_ids(json_logging, telemetry, capsys):
    tracer = telemetry.tracer_provider.get_tracer("test")
    log = structlog.get_logger("t")
    with tracer.start_as_current_span("work") as span:
        log.info("inside")
        ctx = span.get_span_context()
    log.info("outside")
    inside, outside = (json.loads(line) for line in capsys.readouterr().out.splitlines()[-2:])
    assert inside["trace_id"] == format(ctx.trace_id, "032x")
    assert inside["span_id"] == format(ctx.span_id, "016x")
    assert "trace_id" not in outside


def test_log_events_are_exported_redacted_with_trace_context(json_logging, telemetry, log_records):
    tracer = telemetry.tracer_provider.get_tracer("test")
    with tracer.start_as_current_span("work") as span:
        structlog.get_logger("t").warning("rejected", url=f"https://x/?k={CANARY}")
        logging.getLogger("some.library").error("failed for %s", CANARY)
        trace_id = span.get_span_context().trace_id
    records = [r.log_record for r in log_records.get_finished_logs()]
    assert len(records) == 2
    for record in records:
        assert CANARY not in str(record.body)
        assert record.trace_id == trace_id
    body = json.loads(str(records[0].body))
    assert body["event"] == "rejected"
    assert body["trace_id"] == format(trace_id, "032x")


def test_exporter_logs_are_not_fed_back_into_the_export(json_logging, log_records):
    logging.getLogger("opentelemetry.exporter.otlp").warning("collector unreachable")
    assert log_records.get_finished_logs() == ()


async def test_app_engine_queries_are_traced(migrated_url, settings, telemetry, spans):
    db_settings = settings.model_copy(update={"database_url": SecretStr(migrated_url)})
    engine = create_engine(db_settings)
    telemetry.instrument_engine(engine)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()
    db_spans = [s for s in spans.get_finished_spans() if s.kind is SpanKind.CLIENT]
    assert db_spans
    assert db_spans[-1].attributes["db.system"] == "postgresql"


def test_every_metric_name_is_in_the_spec():
    spec = SPEC.read_text()
    for name in metric_names.ALL:
        assert re.search(rf"`{name}(\{{|`)", spec), name
