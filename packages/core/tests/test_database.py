import socket

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text

from homelab_harness.app import create_app
from homelab_harness.db.engine import create_engine
from homelab_harness.db.health import database_check
from homelab_harness.db.url import parse_database_url
from homelab_harness.health import CheckStatus
from homelab_harness.redaction import MASK, redactor
from homelab_harness.settings import Environment, Settings
from homelab_harness_sdk.errors import InvalidInput

PASSWORD = "hh-canary-dbpass-51c0"


def _closed_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.parametrize(
    "raw", ["postgres://u:p@h/db", "postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"]
)
def test_postgres_schemes_pin_the_psycopg_driver(raw):
    assert parse_database_url(raw).drivername == "postgresql+psycopg"


@pytest.mark.parametrize(
    "raw",
    [f"mysql://u:{PASSWORD}@h/db", f"postgresql://u:{PASSWORD}@h", f"::{PASSWORD}::not a url"],
)
def test_bad_urls_are_rejected_without_echoing_them(raw):
    with pytest.raises(InvalidInput) as excinfo:
        parse_database_url(raw)
    assert PASSWORD not in str(excinfo.value)


def test_database_url_is_secret_in_settings_repr():
    s = Settings(database_url=SecretStr(f"postgresql://u:{PASSWORD}@h/db"))
    assert PASSWORD not in repr(s)
    assert PASSWORD not in str(s.model_dump())


def test_create_app_registers_the_database_password_with_the_redactor():
    try:
        create_app(
            Settings(
                env=Environment.TEST, database_url=SecretStr(f"postgresql://u:{PASSWORD}@h/db")
            )
        )
        assert redactor.scrub_text(f"failed for {PASSWORD}") == f"failed for {MASK}"
    finally:
        redactor.clear()


async def test_connections_carry_the_statement_timeout(engine):
    async with engine.connect() as conn:
        assert await conn.scalar(text("SHOW statement_timeout")) == "15s"


async def test_database_check_ok_against_a_live_database(engine):
    result = await database_check(engine)()
    assert result.status is CheckStatus.OK


async def test_database_check_fails_cleanly_when_unreachable():
    url = f"postgresql://harness:{PASSWORD}@127.0.0.1:{_closed_port()}/harness"
    eng = create_engine(Settings(env=Environment.TEST, database_url=SecretStr(url)))
    try:
        result = await database_check(eng)()
    finally:
        await eng.dispose()
    assert result.status is CheckStatus.FAIL
    assert result.detail == "unreachable"  # fixed text: no driver message, host or password


async def test_readyz_reports_a_down_database_as_503():
    url = f"postgresql://harness:{PASSWORD}@127.0.0.1:{_closed_port()}/harness"
    settings = Settings(env=Environment.TEST, database_url=SecretStr(url))
    app = create_app(settings)
    eng = create_engine(settings)
    app.state.readiness.register("database", database_check(eng))
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/readyz")
    finally:
        await eng.dispose()
        redactor.clear()
    assert r.status_code == 503
    assert r.json()["checks"]["database"] == {"status": "fail", "detail": "unreachable"}
    assert PASSWORD not in r.text
