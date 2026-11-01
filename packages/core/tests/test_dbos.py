"""DBOS against the test Postgres.

The example workflow exists only here: it proves the runtime records step
results durably (the core of R-11). The real job engine arrives in Stage 2.
"""

import logging
import socket
import time
import uuid
from collections import Counter

import httpx
import pytest
from dbos import DBOS, SetWorkflowID
from pydantic import SecretStr
from sqlalchemy import text

from homelab_harness.app import create_app
from homelab_harness.jobs.runtime import SYSTEM_SCHEMA, dbos_check, launch_dbos, shutdown_dbos
from homelab_harness.redaction import redactor
from homelab_harness.settings import Environment, Settings

calls: Counter[str] = Counter()


@DBOS.step()
def add_one(x: int) -> int:
    calls["add_one"] += 1
    return x + 1


@DBOS.step()
def double(x: int) -> int:
    calls["double"] += 1
    return x * 2


@DBOS.workflow()
def example_workflow(x: int) -> int:
    return double(add_one(x))


@pytest.fixture
def dbos_runtime(db_settings):
    calls.clear()
    launch_dbos(db_settings)
    yield
    shutdown_dbos()


def test_rerunning_a_workflow_id_returns_the_recorded_result_without_reexecuting(dbos_runtime):
    workflow_id = f"wf-{uuid.uuid4()}"
    with SetWorkflowID(workflow_id):
        assert example_workflow(3) == 8
    assert calls == {"add_one": 1, "double": 1}

    with SetWorkflowID(workflow_id):
        assert example_workflow(3) == 8
    assert calls == {"add_one": 1, "double": 1}  # replayed from the record, not re-run

    status = DBOS.get_workflow_status(workflow_id)
    assert status is not None
    assert status.status == "SUCCESS"
    steps = DBOS.list_workflow_steps(workflow_id)
    assert [s["function_name"].rsplit(".", 1)[-1] for s in steps] == ["add_one", "double"]


def test_resuming_after_a_step_reuses_completed_steps(dbos_runtime):
    # Restarting from the second step, as recovery does after a crash between
    # steps, reuses the first step's recorded output instead of calling it again.
    workflow_id = f"wf-{uuid.uuid4()}"
    with SetWorkflowID(workflow_id):
        example_workflow(5)
    second_step = DBOS.list_workflow_steps(workflow_id)[1]["function_id"]

    handle = DBOS.fork_workflow(workflow_id, second_step)
    assert handle.get_result() == 12
    assert calls == {"add_one": 1, "double": 2}


def test_dbos_logs_go_through_the_redacting_root_handler(dbos_runtime):
    dbos_logger = logging.getLogger("dbos")
    assert dbos_logger.propagate
    assert all(isinstance(h, logging.NullHandler) for h in dbos_logger.handlers)


async def test_dbos_check_reports_ok_when_launched(dbos_runtime):
    assert (await dbos_check()).status == "ok"


async def test_dbos_check_fails_when_not_launched():
    result = await dbos_check()
    assert result.status == "fail"
    assert result.detail == "unavailable"


async def test_app_lifespan_launches_dbos_and_registers_readiness(db_settings, engine):
    app = create_app(db_settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/readyz")
        assert r.status_code == 200
        assert r.json()["checks"] == {
            "database": {"status": "ok", "detail": ""},
            "dbos": {"status": "ok", "detail": ""},
        }
        assert app.state.audit is not None
    assert (await dbos_check()).status == "fail"  # shut down with the app
    async with engine.connect() as conn:  # the loop still works after DBOS shutdown
        schemas = await conn.scalars(
            text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = :s"),
            {"s": SYSTEM_SCHEMA},
        )
        assert schemas.all() == [SYSTEM_SCHEMA]


async def test_startup_fails_fast_when_the_database_is_down():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    canary = "hh-canary-startup-77d1"
    url = f"postgresql://harness:{canary}@127.0.0.1:{port}/harness"
    app = create_app(Settings(env=Environment.TEST, database_url=SecretStr(url)))
    started = time.monotonic()
    try:
        with pytest.raises(Exception) as excinfo:  # noqa: PT011 - any driver error will do
            async with app.router.lifespan_context(app):
                pass
    finally:
        redactor.clear()
    assert time.monotonic() - started < 15
    assert canary not in str(excinfo.value)


async def test_app_without_a_database_starts_with_no_database_checks():
    app = create_app(Settings(env=Environment.TEST))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/readyz")
    assert r.json() == {"status": "ok", "checks": {}}
    assert not hasattr(app.state, "audit")
