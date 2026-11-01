"""Canary-secret checks (R-16): the token secret never shows in str, repr, errors or logs."""

import logging

import httpx
import pytest
from structlog.testing import capture_logs

from homelab_harness_proxmox import ApiToken, Endpoint, ProxmoxClient, SystemTrust
from homelab_harness_sdk.errors import HarnessError, InvalidInput


def test_token_and_client_reprs_hide_the_secret(token, canary_secret):
    client = ProxmoxClient(endpoint=Endpoint(host="pve1"), token=token, trust=SystemTrust())
    for text in (str(token), repr(token), str(client), repr(client)):
        assert canary_secret not in text
    assert "harness@pve!read" in repr(client)


@pytest.mark.parametrize("suffix", ["\n", " ", "\r\nX-Injected: 1", "\x00"])
def test_rejected_secret_is_not_echoed(canary_secret, suffix):
    with pytest.raises(InvalidInput) as raised:
        ApiToken(user="harness@pve", token_id="read", secret=canary_secret + suffix)
    assert canary_secret not in str(raised.value)
    assert canary_secret not in repr(raised.value)


@pytest.mark.parametrize(
    ("user", "token_id"), [("harness", "read"), ("harness@pve!x", "read"), ("harness@pve", "1x")]
)
def test_malformed_token_identity_is_rejected(user, token_id, canary_secret):
    with pytest.raises(InvalidInput):
        ApiToken(user=user, token_id=token_id, secret=canary_secret)


async def test_secret_never_reaches_logs_on_success_or_failure(
    pve, pve_mock, load, canary_secret, caplog
):
    pve_mock.get("/version").mock(return_value=httpx.Response(200, json=load("version/ok")))
    pve_mock.get("/nodes").mock(return_value=httpx.Response(401))
    pve_mock.get("/cluster/status").mock(side_effect=httpx.ConnectError("refused"))
    caplog.set_level(logging.DEBUG)
    with capture_logs() as events:
        await pve.version()
        for call in (pve.list_nodes, pve.cluster_status):
            with pytest.raises(HarnessError) as raised:
                await call()
            assert canary_secret not in str(raised.value)
            assert canary_secret not in repr(raised.value.__cause__)
    assert events, "the adapter logs each request"
    assert any(e["event"] == "proxmox.request_failed" for e in events)
    assert canary_secret not in repr(events)
    assert canary_secret not in caplog.text
