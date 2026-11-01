import base64
import urllib.parse

import pytest

from homelab_harness.redaction import MASK, Redactor

CANARY = "hh-canary-7f3e9c1d-secret"


@pytest.fixture
def redactor():
    r = Redactor()
    r.register(CANARY)
    return r


@pytest.mark.parametrize(
    "encoded",
    [
        CANARY,
        urllib.parse.quote(CANARY, safe=""),
        base64.b64encode(CANARY.encode()).decode(),
        base64.b64encode(CANARY.encode()).decode().rstrip("="),
        CANARY.encode().hex(),
    ],
)
def test_registered_secret_is_masked_in_every_common_encoding(redactor, encoded):
    out = redactor.scrub_text(f"calling api with key={encoded} done")
    assert encoded not in out
    assert MASK in out


def test_sensitive_keys_are_masked_regardless_of_value(redactor):
    event = {
        "event": "proxmox_call",
        "Authorization": "PVEAPIToken=harness@pve!read=abc",
        "api_key": "not-registered-but-sensitive",
        "nested": {"password": "hunter22", "node": "pve1"},
        "headers": [{"cookie": "PVEAuthCookie=xyz"}],
    }
    out = redactor.scrub(event)
    assert out["Authorization"] == MASK
    assert out["api_key"] == MASK
    assert out["nested"] == {"password": MASK, "node": "pve1"}
    assert out["headers"] == [{"cookie": MASK}]
    assert out["event"] == "proxmox_call"


def test_scrub_does_not_mutate_input(redactor):
    event = {"msg": f"x {CANARY}", "token": "abc123456"}
    redactor.scrub(event)
    assert event == {"msg": f"x {CANARY}", "token": "abc123456"}


def test_short_values_are_not_registered():
    r = Redactor()
    r.register("true")
    assert r.scrub_text("feature=true") == "feature=true"


def test_longest_match_wins_so_secrets_are_masked_whole():
    r = Redactor()
    r.register("abcdef")
    r.register("abcdefghijkl")
    assert r.scrub_text("x abcdefghijkl y") == f"x {MASK} y"


def test_empty_and_none_values_under_sensitive_keys_are_left_alone(redactor):
    assert redactor.scrub({"token": None, "password": ""}) == {"token": None, "password": ""}


def test_clear_forgets_registered_values(redactor):
    redactor.clear()
    assert redactor.scrub_text(CANARY) == CANARY
