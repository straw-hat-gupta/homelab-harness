import httpx
import respx
from typer.testing import CliRunner

from homelab_harness_cli.main import app

runner = CliRunner()
BASE = "http://harness.test"


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("hh ")


@respx.mock
def test_health_ready_prints_checks_and_exits_zero():
    respx.get(f"{BASE}/healthz").mock(
        return_value=httpx.Response(200, json={"status": "ok", "version": "0.1.0"})
    )
    respx.get(f"{BASE}/readyz").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "degraded",
                "checks": {
                    "database": {"status": "ok", "detail": ""},
                    "target:pve1": {"status": "degraded", "detail": "unreachable"},
                },
            },
        )
    )
    result = runner.invoke(app, ["health", "--url", BASE])
    assert result.exit_code == 0
    assert "degraded" in result.stdout
    assert "target:pve1 (unreachable)" in result.stdout


@respx.mock
def test_health_failing_exits_one():
    respx.get(f"{BASE}/healthz").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    respx.get(f"{BASE}/readyz").mock(
        return_value=httpx.Response(503, json={"status": "fail", "checks": {}})
    )
    result = runner.invoke(app, ["health", "--url", BASE])
    assert result.exit_code == 1


@respx.mock
def test_health_unreachable_exits_one_without_traceback():
    respx.get(f"{BASE}/healthz").mock(side_effect=httpx.ConnectError("refused"))
    result = runner.invoke(app, ["health", "--url", BASE])
    assert result.exit_code == 1
    assert "unreachable" in result.stderr
