import json
import logging

import pytest
import structlog

from homelab_harness.log_config import configure_logging
from homelab_harness.redaction import redactor
from homelab_harness.settings import Environment, LogFormat, Settings

CANARY = "hh-canary-logging-0451aa"


@pytest.fixture
def json_logging():
    configure_logging(Settings(env=Environment.TEST, log_format=LogFormat.JSON))
    redactor.register(CANARY)
    yield
    redactor.clear()
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


def test_structlog_events_are_json_and_redacted(json_logging, capsys):
    structlog.get_logger("t").info("calling", url=f"https://x/?k={CANARY}", token="abcdefgh")
    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "calling"
    assert record["level"] == "info"
    assert CANARY not in line
    assert record["token"] == "[REDACTED]"


def test_stdlib_library_logs_are_also_redacted(json_logging, capsys):
    logging.getLogger("some.library").warning("connect failed for secret %s", CANARY)
    out = capsys.readouterr().out
    assert CANARY not in out
    assert "connect failed" in out
