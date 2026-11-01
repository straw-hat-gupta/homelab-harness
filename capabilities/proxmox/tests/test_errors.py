"""Error mapping: every failure class lands on the shared SDK types, and no body leaks."""

import asyncio
import secrets
import threading
from datetime import UTC, datetime

import httpx
import pytest

from homelab_harness_proxmox import TlsVerificationFailed, UnexpectedResponse
from homelab_harness_proxmox.errors import map_status_error, parse_retry_after
from homelab_harness_sdk.errors import (
    AuthRejected,
    Conflict,
    HarnessError,
    InvalidInput,
    NotFound,
    PermissionDenied,
    RateLimited,
    TargetUnavailable,
)

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def body_canary() -> str:
    return f"CANARY_BODY_{secrets.token_hex(8)}"


# status, reason phrase (PVE puts its message here), body message, expected type
TABLE = [
    (401, "authentication failure", "", AuthRejected),
    (403, "Permission check failed (/nodes/pve1, Sys.Audit)", "", PermissionDenied),
    (404, "Not Found", "", NotFound),
    (500, "Configuration file 'nodes/pve1/qemu-server/999.conf' does not exist", "", NotFound),
    (500, "storage 'nope' does not exist", "", NotFound),
    (500, "can't lock file '/var/lock/qemu-server/lock-101.conf' - got timeout", "", Conflict),
    (500, "VM is locked (backup)", "", Conflict),
    (500, "Internal Server Error", "CT 200 is locked (snapshot)", Conflict),
    (500, "VM 101 already exists on node 'pve2'", "", Conflict),
    (409, "Conflict", "", Conflict),
    (429, "Too Many Requests", "", RateLimited),
    (400, "Parameter verification failed.", "", InvalidInput),
    (501, "Method 'GET /nodes/pve1/nope' not implemented", "", NotFound),
    (500, "Internal Server Error", "", TargetUnavailable),
    (502, "Bad Gateway", "", TargetUnavailable),
    (503, "Service Unavailable", "", TargetUnavailable),
    (595, "Connection refused", "", TargetUnavailable),
    (595, "No route to host", "", TargetUnavailable),
]


@pytest.mark.parametrize(("status", "reason", "message", "expected"), TABLE)
async def test_http_failures_map_to_sdk_errors_without_leaking_the_body(
    pve, pve_mock, body_canary, canary_secret, status, reason, message, expected
):
    body = {"data": None, "message": f"{message} {body_canary}", "errors": {"vmid": body_canary}}
    pve_mock.get("/nodes/pve1/status").mock(
        return_value=httpx.Response(
            status,
            json=body,
            extensions={"reason_phrase": f"{reason} {body_canary}".encode()},
        )
    )
    with pytest.raises(HarnessError) as raised:
        await pve.node_status("pve1")
    error = raised.value
    assert type(error) is expected
    assert error.target == "pve1.lab.invalid"
    assert "GET /nodes/pve1/status" in error.safe_message
    for leaked in (body_canary, canary_secret):
        assert leaked not in str(error)
        assert leaked not in repr(error)
        assert all(leaked not in str(arg) for arg in error.args)


async def test_rate_limit_carries_retry_after(pve, pve_mock):
    pve_mock.get("/version").mock(return_value=httpx.Response(429, headers={"Retry-After": "7"}))
    with pytest.raises(RateLimited) as raised:
        await pve.version()
    assert raised.value.retry_after_seconds == 7.0
    assert raised.value.retryable is True


@pytest.mark.parametrize(
    ("header", "seconds"),
    [
        (None, None),
        ("0", 0.0),
        ("120", 120.0),
        ("Sun, 01 Nov 2026 12:00:30 GMT", 30.0),
        ("Sun, 01 Nov 2026 11:00:00 GMT", 0.0),  # in the past
        ("soon", None),
    ],
)
def test_parse_retry_after(header, seconds):
    assert parse_retry_after(header, now=NOW) == seconds


def test_auth_and_permission_errors_are_not_retryable():
    common = {
        "reason": "",
        "body": None,
        "headers": {},
        "method": "GET",
        "path": "/x",
        "target": "h",
        "now": NOW,
    }
    assert map_status_error(status=401, **common).retryable is False
    assert map_status_error(status=403, **common).retryable is False
    assert map_status_error(status=595, **common).retryable is True


@pytest.mark.parametrize(
    ("exc", "expected_text"),
    [
        (httpx.ConnectError("All connection attempts failed"), "could not reach"),
        (httpx.ConnectTimeout("timed out"), "did not answer in time"),
        # A read timeout on a GET is not ambiguous: nothing was changed.
        (httpx.ReadTimeout("timed out"), "did not answer in time"),
        (httpx.RemoteProtocolError("Server disconnected"), "could not reach"),
        (httpx.PoolTimeout("pool"), "did not answer in time"),
    ],
)
async def test_transport_errors_on_reads_are_target_unavailable(pve, pve_mock, exc, expected_text):
    pve_mock.get("/version").mock(side_effect=exc)
    with pytest.raises(TargetUnavailable) as raised:
        await pve.version()
    assert type(raised.value) is TargetUnavailable
    assert expected_text in raised.value.safe_message
    assert raised.value.retryable is True


def test_cyclic_exception_chain_does_not_hang(pve, pve_mock):
    # Regression: the contract kit's repeated failures produced a chain whose
    # __context__ points back at itself, and the TLS-cause walk looped forever.
    outer = httpx.ConnectError("refused")
    inner = OSError("refused")
    outer.__context__ = inner
    inner.__context__ = outer
    pve_mock.get("/version").mock(side_effect=outer)
    # The walk is synchronous, so run the call on its own loop in a thread: a
    # regression fails the join instead of hanging the suite.
    errors = []

    def call():
        try:
            asyncio.run(pve.version())
        except TargetUnavailable as exc:
            errors.append(exc)

    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive(), "mapping a cyclic exception chain did not terminate"
    assert errors
    assert "could not reach" in errors[0].safe_message


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"no": "data"}),
        httpx.Response(200, json=[1, 2]),
    ],
)
async def test_unreadable_success_bodies(pve, pve_mock, response):
    pve_mock.get("/version").mock(return_value=response)
    with pytest.raises(UnexpectedResponse):
        await pve.version()


async def test_wrong_shape_is_unexpected_response_without_echoing_values(
    pve, pve_mock, body_canary
):
    pve_mock.get("/nodes").mock(
        return_value=httpx.Response(200, json={"data": [{"node": body_canary}]})  # no status
    )
    with pytest.raises(UnexpectedResponse) as raised:
        await pve.list_nodes()
    assert body_canary not in str(raised.value)
    # The pydantic error (which quotes the values) is deliberately not chained.
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_tls_failures_are_unavailable_but_never_retried():
    error = TlsVerificationFailed("mismatch", target="h")
    assert isinstance(error, TargetUnavailable)
    assert error.retryable is False
