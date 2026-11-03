"""Pure auth logic: recovery codes, rate limits, redirect URIs, CIMD rules, passkeys, settings."""

import json
import secrets
from datetime import timedelta

import pytest
from mcp.shared.auth import InvalidRedirectUriError
from pydantic import AnyUrl, ValidationError

from homelab_harness.auth import passkeys
from homelab_harness.auth.cimd import (
    CimdError,
    cache_lifetime,
    check_client_id_url,
    is_public_address,
    parse_document,
)
from homelab_harness.auth.client_rules import (
    HarnessClient,
    check_redirect_uri,
    cimd_audit_id,
    redirect_matches,
)
from homelab_harness.auth.config import auth_config
from homelab_harness.auth.passkeys import PasskeyError
from homelab_harness.auth.ratelimit import Limit, RateLimiter
from homelab_harness.auth.recovery import generate_codes, hash_secret, split_code, verify_secret
from homelab_harness.settings import Settings

CLIENT = "https://client.example.com/oauth/metadata.json"


# --- recovery codes ----------------------------------------------------------


def test_recovery_codes_are_unique_and_normalize():
    codes = generate_codes()
    assert len(codes) == 10
    assert len({c.split("-")[0] for c in codes}) == 10
    lookup, secret = split_code(codes[0].lower().replace("-", " "))
    assert f"{lookup}{secret}" == codes[0].replace("-", "")
    assert split_code("not-a-code") is None
    assert split_code("0000-0000-0000-0000") is None  # 0 is not in the alphabet


def test_recovery_hash_verifies_only_the_right_secret():
    stored = hash_secret("ABCDEFGHJKMN")
    assert stored.startswith("scrypt$")
    assert verify_secret("ABCDEFGHJKMN", stored)
    assert not verify_secret("ABCDEFGHJKMP", stored)
    assert not verify_secret("ABCDEFGHJKMN", "scrypt$broken")
    assert hash_secret("ABCDEFGHJKMN") != stored  # salted


# --- rate limits -------------------------------------------------------------


def test_rate_limit_per_client_and_total():
    now = [0.0]
    limiter = RateLimiter(
        {"x": Limit(per_client=2, total=3, window_seconds=60)}, clock=lambda: now[0]
    )
    assert limiter.check("x", "a").allowed
    assert limiter.check("x", "a").allowed
    refused = limiter.check("x", "a")
    assert not refused.allowed
    assert refused.retry_after_seconds == 60
    # The third request from anyone else hits the shared total.
    assert not limiter.check("x", "b").allowed
    now[0] = 61
    assert limiter.check("x", "a").allowed


# --- redirect URIs and labels ------------------------------------------------


@pytest.mark.parametrize(
    ("uri", "ok"),
    [
        ("https://app.example.com/cb", True),
        ("http://localhost:3000/callback", True),
        ("http://127.0.0.1/callback", True),
        ("http://[::1]:9000/cb", True),
        ("http://app.example.com/cb", False),
        ("https://app.example.com/cb#frag", False),
        ("https://user:pw@app.example.com/cb", False),
        ("javascript:alert(1)", False),
        ("/relative", False),
    ],
)
def test_redirect_uri_rules(uri, ok):
    assert (check_redirect_uri(uri) is None) is ok


def test_loopback_redirects_match_on_any_port_only():
    assert redirect_matches("http://127.0.0.1:53111/callback", "http://127.0.0.1/callback")
    assert redirect_matches("http://localhost:9/cb", "http://localhost:8080/cb")
    assert not redirect_matches("http://localhost:9/other", "http://localhost/cb")
    assert not redirect_matches("https://a.example/cb2", "https://a.example/cb")
    assert not redirect_matches("https://a.example:444/cb", "https://a.example/cb")


def test_client_validates_redirect_uri_strings():
    client = HarnessClient(
        client_id=CLIENT, redirect_uris=[AnyUrl("http://127.0.0.1/callback")], client_name="x"
    )
    assert str(client.validate_redirect_uri(AnyUrl("http://127.0.0.1:40000/callback")))
    assert client.validate_redirect_uri(None) == AnyUrl("http://127.0.0.1/callback")
    with pytest.raises(InvalidRedirectUriError):
        client.validate_redirect_uri(AnyUrl("https://evil.example/callback"))


def test_cimd_audit_labels_fit_the_audit_actor_rule():
    assert cimd_audit_id(CLIENT) == "cimd:client.example.com:oauth:metadata.json"
    assert cimd_audit_id("https://h.example:8443/a?b=c") == "cimd:h.example.8443:a:b-c"
    long = "https://h.example/" + "a" * 600
    label = cimd_audit_id(long)
    assert len(label) <= 150
    assert label != cimd_audit_id(long + "b")


# --- client ID metadata documents --------------------------------------------


@pytest.mark.parametrize(
    "client_id",
    [
        "http://client.example.com/meta.json",
        "https://client.example.com",
        "https://client.example.com/",
        "https://client.example.com/a/../meta.json",
        "https://user:pw@client.example.com/meta.json",
        "https://client.example.com/meta.json#x",
        "https://" + "a" * 600 + ".example/meta.json",
    ],
)
def test_cimd_url_rules(client_id):
    with pytest.raises(CimdError):
        check_client_id_url(client_id)


def test_cimd_url_accepts_a_port():
    assert check_client_id_url("https://Client.example.com:8443/m.json") == (
        "client.example.com",
        8443,
    )


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("93.184.215.14", True),
        ("2606:4700::1111", True),
        ("127.0.0.1", False),
        ("10.0.0.5", False),
        ("192.168.1.1", False),
        ("172.16.0.1", False),
        ("169.254.169.254", False),  # cloud metadata
        ("100.100.100.100", False),  # Tailscale CGNAT range
        ("::1", False),
        ("fd7a:115c:a1e0::1", False),  # Tailscale ULA
        ("::ffff:10.0.0.1", False),  # IPv4-mapped private
        ("224.0.0.1", False),
        ("0.0.0.0", False),  # noqa: S104 - an address under test, not a bind
        ("not-an-ip", False),
    ],
)
def test_public_address_rules(address, public):
    assert is_public_address(address) is public


def _doc(**overrides):
    doc = {
        "client_id": CLIENT,
        "client_name": "Example Client",
        "redirect_uris": ["http://127.0.0.1/callback"],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
    }
    doc.update(overrides)
    return json.dumps(doc).encode()


def test_cimd_document_is_validated():
    doc = parse_document(CLIENT, _doc(), cache_control="max-age=60")
    assert doc.client_name == "Example Client"
    assert doc.redirect_uris == ["http://127.0.0.1/callback"]
    assert doc.cache_for == timedelta(minutes=5)  # clamped up


@pytest.mark.parametrize(
    ("body", "match"),
    [
        (b"not json", "not valid JSON"),
        (b"[]", "JSON object"),
        (_doc(client_id="https://other.example.com/m.json"), "does not match"),
        (_doc(client_secret="x"), "client_secret"),
        (_doc(token_endpoint_auth_method="client_secret_basic"), "public clients"),
        (_doc(grant_types=["client_credentials"]), "authorization_code"),
        (_doc(client_name=""), "client_name"),
        (_doc(redirect_uris=[]), "redirect_uris"),
        (_doc(redirect_uris=["http://evil.example/cb"]), "https"),
        (_doc(redirect_uris=["https://a.example/cb"] * 11), "more than"),
    ],
)
def test_cimd_document_refusals(body, match):
    with pytest.raises(CimdError, match=match):
        parse_document(CLIENT, body, cache_control=None)


def test_cache_lifetime_is_clamped():
    assert cache_lifetime(None) == timedelta(hours=1)
    assert cache_lifetime("max-age=999999") == timedelta(hours=24)
    assert cache_lifetime("public, max-age=7200") == timedelta(hours=2)
    assert cache_lifetime("no-store") == timedelta(minutes=5)


# --- passkey ceremonies (py_webauthn) ----------------------------------------


ORIGIN = "https://harness.example.ts.net"
RP_ID = "harness.example.ts.net"


def test_registration_and_assertion_round_trip(soft_authenticator):
    challenge = secrets.token_bytes(32)
    options = passkeys.registration_options(
        rp_id=RP_ID, user_handle=b"\x01" * 32, challenge=challenge, existing=[b"\x02" * 16]
    )
    assert options["rp"]["id"] == RP_ID
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert options["excludeCredentials"][0]["type"] == "public-key"
    authenticator = soft_authenticator(origin=ORIGIN)
    new = passkeys.verify_registration(
        credential=authenticator.register(options), challenge=challenge, rp_id=RP_ID, origin=ORIGIN
    )
    assert new.credential_id == authenticator.credential_id

    login_challenge = secrets.token_bytes(32)
    request = passkeys.authentication_options(
        rp_id=RP_ID, challenge=login_challenge, allowed=[new.credential_id]
    )
    count = passkeys.verify_authentication(
        credential=authenticator.assertion(request),
        challenge=login_challenge,
        rp_id=RP_ID,
        origin=ORIGIN,
        public_key=new.public_key,
        sign_count=new.sign_count,
    )
    assert count == 1


def test_passkey_verification_refusals(soft_authenticator):
    challenge = secrets.token_bytes(32)
    options = passkeys.registration_options(
        rp_id=RP_ID, user_handle=b"\x01" * 32, challenge=challenge, existing=[]
    )
    authenticator = soft_authenticator(origin=ORIGIN)
    with pytest.raises(PasskeyError):  # phishing origin
        passkeys.verify_registration(
            credential=authenticator.register(options, origin="https://evil.example"),
            challenge=challenge,
            rp_id=RP_ID,
            origin=ORIGIN,
        )
    with pytest.raises(PasskeyError):  # presence alone is not enough
        passkeys.verify_registration(
            credential=soft_authenticator(origin=ORIGIN, user_verified=False).register(options),
            challenge=challenge,
            rp_id=RP_ID,
            origin=ORIGIN,
        )
    new = passkeys.verify_registration(
        credential=authenticator.register(options), challenge=challenge, rp_id=RP_ID, origin=ORIGIN
    )
    request = passkeys.authentication_options(rp_id=RP_ID, challenge=challenge, allowed=[])
    with pytest.raises(PasskeyError):  # bad signature
        passkeys.verify_authentication(
            credential=authenticator.assertion(request, tamper=True),
            challenge=challenge,
            rp_id=RP_ID,
            origin=ORIGIN,
            public_key=new.public_key,
            sign_count=0,
        )
    with pytest.raises(PasskeyError):  # wrong challenge (a replay of another ceremony)
        passkeys.verify_authentication(
            credential=authenticator.assertion(request),
            challenge=secrets.token_bytes(32),
            rp_id=RP_ID,
            origin=ORIGIN,
            public_key=new.public_key,
            sign_count=0,
        )


# --- settings ----------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://harness.example.ts.net",
        "https://harness.example.ts.net/mcp",
        "https://harness.example.ts.net?x=1",
        "https://u:p@harness.example.ts.net",
    ],
)
def test_public_url_must_be_an_https_origin(url):
    with pytest.raises(ValidationError):
        Settings(public_url=url)


def test_auth_config_derives_everything_from_public_url():
    assert auth_config(Settings()) is None
    config = auth_config(Settings(public_url="https://Harness.example.ts.net:443"))
    assert config is not None
    assert config.issuer == "https://harness.example.ts.net"
    assert config.resource == "https://harness.example.ts.net/mcp"
    assert config.rp_id == "harness.example.ts.net"
    assert config.session_cookie.startswith("__Host-")
    local = auth_config(Settings(public_url="http://localhost:8080"))
    assert local is not None
    assert local.origin == "http://localhost:8080"
    assert not local.secure_cookies
