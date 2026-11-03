"""Fetching client ID metadata documents: SSRF limits, mocked at the HTTP boundary (respx)."""

import asyncio
import json

import httpx
import pytest
import respx

from homelab_harness.auth.cimd import MAX_DOCUMENT_BYTES, CimdError, CimdFetcher

CLIENT = "https://client.example.com/oauth/metadata.json"
PINNED = "https://93.184.215.14/oauth/metadata.json"


def resolver(*addresses):
    calls = []

    async def resolve(host, port):
        calls.append((host, port))
        return list(addresses)

    resolve.calls = calls
    return resolve


def document(**overrides):
    doc = {
        "client_id": CLIENT,
        "client_name": "Example",
        "redirect_uris": ["http://127.0.0.1/callback"],
    }
    doc.update(overrides)
    return doc


@pytest.fixture
def http():
    with respx.mock(assert_all_called=False) as router:
        yield router


async def test_fetch_pins_the_checked_address_and_keeps_the_name_for_tls(http):
    route = http.get(PINNED).mock(return_value=httpx.Response(200, json=document()))
    resolve = resolver("93.184.215.14")
    doc = await CimdFetcher(resolver=resolve).fetch(CLIENT)
    assert doc.client_name == "Example"
    assert resolve.calls == [("client.example.com", 443)]
    request = route.calls.last.request
    assert request.headers["host"] == "client.example.com"
    assert request.extensions["sni_hostname"] == "client.example.com"


@pytest.mark.parametrize(
    "addresses",
    [("127.0.0.1",), ("10.1.2.3",), ("100.101.102.103",), ("93.184.215.14", "192.168.0.10"), ()],
)
async def test_private_or_mixed_addresses_are_refused_before_any_request(http, addresses):
    route = http.get(url__regex=r".*").mock(return_value=httpx.Response(200, json=document()))
    with pytest.raises(CimdError, match=r"non-public|does not resolve"):
        await CimdFetcher(resolver=resolver(*addresses)).fetch(CLIENT)
    assert not route.called


async def test_http_scheme_is_refused_without_resolving():
    resolve = resolver("93.184.215.14")
    with pytest.raises(CimdError, match="https"):
        await CimdFetcher(resolver=resolve).fetch("http://client.example.com/m.json")
    assert resolve.calls == []


async def test_oversize_documents_are_refused(http):
    big = json.dumps(document(client_name="x" * MAX_DOCUMENT_BYTES)).encode()
    http.get(PINNED).mock(
        return_value=httpx.Response(200, content=big, headers={"content-type": "application/json"})
    )
    with pytest.raises(CimdError, match="too large"):
        await CimdFetcher(resolver=resolver("93.184.215.14")).fetch(CLIENT)


async def test_streamed_oversize_is_cut_off(http):
    async def chunks():
        for _ in range(10):
            yield b" " * 1024

    http.get(PINNED).mock(
        return_value=httpx.Response(
            200, content=chunks(), headers={"content-type": "application/json"}
        )
    )
    with pytest.raises(CimdError, match="too large"):
        await CimdFetcher(resolver=resolver("93.184.215.14")).fetch(CLIENT)


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (httpx.Response(302, headers={"location": "http://169.254.169.254/"}), "HTTP 302"),
        (httpx.Response(404), "HTTP 404"),
        (httpx.Response(200, text="<html>", headers={"content-type": "text/html"}), "not JSON"),
        (httpx.Response(200, json=document(client_id="https://x.example/m.json")), "match"),
    ],
)
async def test_bad_responses_are_refused(http, response, match):
    http.get(PINNED).mock(return_value=response)
    with pytest.raises(CimdError, match=match):
        await CimdFetcher(resolver=resolver("93.184.215.14")).fetch(CLIENT)


async def test_network_errors_and_timeouts_are_refused(http):
    http.get(PINNED).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(CimdError, match="could not be fetched"):
        await CimdFetcher(resolver=resolver("93.184.215.14")).fetch(CLIENT)

    async def slow(host, port):
        await asyncio.sleep(5)
        return ["93.184.215.14"]

    with pytest.raises(CimdError, match="timed out"):
        await CimdFetcher(resolver=slow, timeout_seconds=0.05).fetch(CLIENT)
