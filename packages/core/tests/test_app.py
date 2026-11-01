import asyncio

import httpx
import pytest

from homelab_harness import __version__
from homelab_harness.app import create_app
from homelab_harness.health import CheckResult, CheckStatus, ReadinessRegistry
from homelab_harness.settings import Environment, Settings


@pytest.fixture
def app():
    return create_app(Settings(env=Environment.TEST))


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _const(status, detail=""):
    async def check():
        return CheckResult(status, detail)

    return check


async def test_healthz_reports_version(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__}


async def test_readyz_is_ok_with_no_checks(client):
    r = await client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "checks": {}}


async def test_degraded_check_still_serves(app, client):
    app.state.readiness.register("database", _const(CheckStatus.OK))
    app.state.readiness.register("target:pve1", _const(CheckStatus.DEGRADED, "unreachable"))
    r = await client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"
    assert r.json()["checks"]["target:pve1"] == {"status": "degraded", "detail": "unreachable"}


async def test_failing_check_returns_503(app, client):
    app.state.readiness.register("database", _const(CheckStatus.FAIL, "connection refused"))
    r = await client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["status"] == "fail"


async def test_raising_or_slow_checks_count_as_failed_without_leaking_messages():
    registry = ReadinessRegistry(timeout_seconds=0.05)

    async def boom():
        raise RuntimeError("password=hunter2 in a stack trace")

    async def slow():
        await asyncio.sleep(1)
        return CheckResult(CheckStatus.OK)

    registry.register("boom", boom)
    registry.register("slow", slow)
    report = await registry.run()
    assert report.status is CheckStatus.FAIL
    assert report.checks["boom"].detail == "check raised RuntimeError"
    assert report.checks["slow"].detail == "timed out"


def test_duplicate_check_names_are_rejected():
    registry = ReadinessRegistry()
    registry.register("database", _const(CheckStatus.OK))
    with pytest.raises(ValueError, match="already registered"):
        registry.register("database", _const(CheckStatus.OK))


def test_api_docs_are_disabled_in_production():
    assert create_app(Settings(env=Environment.PROD)).docs_url is None
    assert create_app(Settings(env=Environment.DEV)).docs_url == "/docs"
