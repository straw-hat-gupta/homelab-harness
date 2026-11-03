"""The owner login and the OAuth 2.1 authorization server, end to end over HTTP.

The ASGI app runs against real Postgres (a fresh database per test, since there
is only ever one owner). Passkeys are a software authenticator whose responses
py_webauthn really verifies. Client metadata documents are fetched through the
real fetcher with a fake resolver and respx at the HTTP boundary.
"""

import base64
import dataclasses
import hashlib
import logging
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import httpx2
import pytest
import respx
import structlog
from mcp import Client
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientMetadata
from pydantic import AnyUrl, SecretStr
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from homelab_harness.app import create_app
from homelab_harness.audit.queries import recent_events
from homelab_harness.auth.cimd import CimdFetcher
from homelab_harness.auth.models import OAuthGrant, OAuthToken, Owner
from homelab_harness.auth.owner_cli import main as owner_main
from homelab_harness.auth.ratelimit import DEFAULT_LIMITS, RateLimiter
from homelab_harness.log_config import configure_logging
from homelab_harness.mcp.clients import ClientRole, create_client
from homelab_harness.redaction import redactor
from homelab_harness.settings import Environment, LogFormat, Settings, get_settings
from homelab_harness_sdk.errors import Conflict, InvalidInput

ORIGIN = "http://localhost:8080"
RESOURCE = ORIGIN + "/mcp"
CLIENT = "https://client.example.com/oauth/metadata.json"
PINNED = "https://93.184.215.14/oauth/metadata.json"
REDIRECT = "http://127.0.0.1/callback"
CALLBACK = "http://127.0.0.1:53682/callback"
COOKIE = "hh_owner"


async def public_resolver(host, port):
    return ["93.184.215.14"]


@pytest.fixture
def cimd():
    with respx.mock(assert_all_called=False) as router:
        router.get(PINNED).mock(
            return_value=httpx.Response(
                200,
                json={
                    "client_id": CLIENT,
                    "client_name": "Example MCP Client",
                    "redirect_uris": [REDIRECT],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "token_endpoint_auth_method": "none",
                },
            )
        )
        yield router


def make_app(database_url, **overrides):
    settings = Settings(
        env=Environment.TEST,
        database_url=SecretStr(database_url),
        **{"public_url": ORIGIN, **overrides},
    )
    application = create_app(settings)
    application.state.cimd_fetcher = CimdFetcher(resolver=public_resolver)
    return application


@pytest.fixture
async def app(fresh_migrated_url, serve_app, cimd):
    application = make_app(fresh_migrated_url)
    async with serve_app(application):
        yield application
    redactor.clear()


def http(app, base=ORIGIN, **headers):
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url=base, headers=headers
    )


@pytest.fixture
async def browser(app):
    async with http(app, Origin=ORIGIN) as client:
        yield client


@pytest.fixture
def passkey(soft_authenticator):
    return soft_authenticator(origin=ORIGIN)


async def enroll(app, browser, passkey):
    enrollment = await app.state.auth.owner.start_enrollment()
    token = enrollment.url.split("#token=", 1)[1]
    start = await browser.post("/owner/enroll/options", json={"token": token})
    assert start.status_code == 200, start.text
    body = start.json()
    done = await browser.post(
        "/owner/enroll/verify",
        json={
            "token": token,
            "challenge_id": body["challenge_id"],
            "credential": passkey.register(body["options"]),
        },
    )
    assert done.status_code == 200, done.text
    browser.headers["Cookie"] = f"{COOKIE}={done.cookies[COOKIE]}"
    return enrollment, token


@pytest.fixture
async def owner(app, browser, passkey):
    enrollment, _ = await enroll(app, browser, passkey)
    return enrollment


async def audit_events(app, limit):
    async with app.state.db_sessions() as session:
        return await recent_events(session, limit=limit)


def pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


def authorize_params(challenge, **overrides):
    params = {
        "response_type": "code",
        "client_id": CLIENT,
        "redirect_uri": CALLBACK,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "st-" + secrets.token_hex(4),
        "scope": "mcp",
        "resource": RESOURCE,
    }
    params.update(overrides)
    return {k: v for k, v in params.items() if v is not None}


def query(location):
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}


async def consent(browser, location, decision="approve"):
    page = await browser.get(location)
    assert page.status_code == 200, page.text
    csrf = re.search(r'name=csrf value="([^"]+)"', page.text).group(1)
    request_id = query(location)["request"]
    return await browser.post(
        "/oauth/consent", data={"request": request_id, "csrf": csrf, "decision": decision}
    )


async def get_code(browser, client_id=CLIENT, redirect_uri=CALLBACK):
    verifier, challenge = pkce()
    params = authorize_params(challenge, client_id=client_id, redirect_uri=redirect_uri)
    start = await browser.get("/oauth/authorize", params=params)
    assert start.status_code == 302, start.text
    decided = await consent(browser, start.headers["location"])
    assert decided.status_code == 303
    answer = query(decided.headers["location"])
    assert answer["state"] == params["state"]
    assert answer["iss"] == ORIGIN
    return answer["code"], verifier


async def exchange(client, code, verifier, *, client_id=CLIENT, **extra):
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": CALLBACK,
        "client_id": client_id,
        "code_verifier": verifier,
        "resource": RESOURCE,
        **extra,
    }
    return await client.post("/oauth/token", data=data)


async def refresh(client, refresh_token, client_id=CLIENT):
    return await client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "resource": RESOURCE,
        },
    )


async def tokens_for(app, browser):
    code, verifier = await get_code(browser)
    async with http(app) as client:
        response = await exchange(client, code, verifier)
    assert response.status_code == 200, response.text
    return response.json()


async def mcp_status(app, token):
    """Status of a bare MCP request with this bearer token."""
    async with http(app, Authorization=f"Bearer {token}") as client:
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
        )
    return response


def mcp_client(app, token):
    transport = streamable_http_client(
        RESOURCE, http_client=http(app, Authorization=f"Bearer {token}")
    )
    return Client(transport, mode="auto", cache=None)


# --- discovery ----------------------------------------------------------------


async def test_metadata_and_the_401_challenge(app):
    async with http(app) as client:
        as_meta = (await client.get("/.well-known/oauth-authorization-server")).json()
        prm = (await client.get("/.well-known/oauth-protected-resource/mcp")).json()
        prm_root = (await client.get("/.well-known/oauth-protected-resource")).json()
        unauthenticated = await client.post("/mcp", json={})
    assert as_meta["issuer"] == ORIGIN
    assert as_meta["authorization_endpoint"] == ORIGIN + "/oauth/authorize"
    assert as_meta["token_endpoint"] == ORIGIN + "/oauth/token"
    assert as_meta["registration_endpoint"] == ORIGIN + "/oauth/register"
    assert as_meta["code_challenge_methods_supported"] == ["S256"]
    assert as_meta["grant_types_supported"] == ["authorization_code", "refresh_token"]
    assert as_meta["token_endpoint_auth_methods_supported"] == ["none"]
    assert as_meta["client_id_metadata_document_supported"] is True
    assert as_meta["authorization_response_iss_parameter_supported"] is True
    assert prm == prm_root
    assert prm == {
        "resource": RESOURCE,
        "authorization_servers": [ORIGIN],
        "scopes_supported": ["mcp"],
        "bearer_methods_supported": ["header"],
        "resource_name": "homelab-harness",
    }
    assert unauthenticated.status_code == 401
    challenge = unauthenticated.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert f'resource_metadata="{ORIGIN}/.well-known/oauth-protected-resource/mcp"' in challenge


# --- owner enrollment, login, recovery ------------------------------------------


async def test_enrollment_link_is_single_use_and_a_second_owner_is_refused(app, browser, passkey):
    enrollment, token = await enroll(app, browser, passkey)
    assert len(enrollment.recovery_codes) == 10
    again = await browser.post("/owner/enroll/options", json={"token": token})
    assert again.status_code == 401
    with pytest.raises(Conflict, match="only one owner"):
        await app.state.auth.owner.start_enrollment()
    async with app.state.db_sessions.begin() as session:
        session.add(Owner(user_handle=b"x" * 32))
        with pytest.raises(IntegrityError, match="uq_owner_singleton"):
            await session.flush()
        await session.rollback()
    added = await app.state.auth.owner.start_enrollment(add_passkey=True)
    assert added.recovery_codes is None


async def test_passkey_login_and_challenge_replay(app, browser, passkey, owner):
    async with http(app, Origin=ORIGIN) as fresh:
        start = (await fresh.post("/owner/login/options")).json()
        assertion = passkey.assertion(start["options"])
        body = {"challenge_id": start["challenge_id"], "credential": assertion, "next": "//evil"}
        done = await fresh.post("/owner/login/verify", json=body)
        assert done.status_code == 200
        assert done.json()["redirect"] == "/owner/login"  # no open redirect
        assert COOKIE in done.cookies
        replay = await fresh.post("/owner/login/verify", json=body)
        assert replay.status_code == 401
        start = (await fresh.post("/owner/login/options")).json()
        bad = passkey.assertion(start["options"], tamper=True)
        refused = await fresh.post(
            "/owner/login/verify", json={"challenge_id": start["challenge_id"], "credential": bad}
        )
        assert refused.status_code == 401


async def test_cross_origin_owner_requests_are_refused(app, owner):
    async with http(app, Origin="https://evil.example") as evil:
        assert (await evil.post("/owner/login/options")).status_code == 403
        recovery = await evil.post("/owner/login/recovery", data={"code": owner.recovery_codes[0]})
        assert recovery.status_code == 403


async def test_recovery_code_works_once(app, owner):
    code = owner.recovery_codes[0]
    async with http(app, Origin=ORIGIN) as fresh:
        first = await fresh.post(
            "/owner/login/recovery", data={"code": code.lower(), "next": "/owner/login"}
        )
        assert first.status_code == 303
        assert COOKIE in first.cookies
        second = await fresh.post("/owner/login/recovery", data={"code": code})
        assert second.status_code == 401
        assert "not valid" in second.text
    events = await audit_events(app, 20)
    logins = [e for e in events if e.kind == "owner.login"]
    assert logins[0].data == {"method": "recovery_code", "codes_left": 9}


async def test_regenerated_codes_replace_the_old_ones(app, owner):
    fresh_codes = await app.state.auth.owner.regenerate_recovery_codes()
    async with http(app, Origin=ORIGIN) as client:
        old = await client.post("/owner/login/recovery", data={"code": owner.recovery_codes[1]})
        new = await client.post("/owner/login/recovery", data={"code": fresh_codes[0]})
    assert old.status_code == 401
    assert new.status_code == 303


async def test_idle_sessions_expire(app, browser, owner):
    service = app.state.auth.owner
    cookie = browser.headers["Cookie"].split("=", 1)[1]
    assert await service.session_for(cookie) is not None
    async with app.state.db_sessions.begin() as session:
        await session.execute(
            text("UPDATE owner_sessions SET last_seen_at = now() - interval '16 minutes'")
        )
    assert await service.session_for(cookie) is None


def test_owner_cli_enrolls_once(fresh_migrated_url, monkeypatch, capsys):
    monkeypatch.setenv("HH_DATABASE_URL", fresh_migrated_url)
    monkeypatch.setenv("HH_PUBLIC_URL", "https://harness.example.ts.net")
    get_settings.cache_clear()
    try:
        owner_main(["enroll"])
        out = capsys.readouterr().out
        assert "https://harness.example.ts.net/owner/enroll#token=" in out
        assert len(re.findall(r"^  [0-9A-Z]{4}(-[0-9A-Z]{4}){3}$", out, re.M)) == 10
        owner_main(["enroll"])  # not enrolled yet: a fresh link and fresh codes
        with pytest.raises(SystemExit, match="no owner is enrolled"):
            owner_main(["recovery-codes"])
    finally:
        get_settings.cache_clear()


async def test_secure_cookie_flags_over_https(fresh_migrated_url, serve_app, soft_authenticator):
    origin = "https://harness.example.ts.net"
    application = make_app(fresh_migrated_url, public_url=origin)
    async with serve_app(application), http(application, base=origin, Origin=origin) as client:
        enrollment = await application.state.auth.owner.start_enrollment()
        token = enrollment.url.split("#token=", 1)[1]
        start = (await client.post("/owner/enroll/options", json={"token": token})).json()
        done = await client.post(
            "/owner/enroll/verify",
            json={
                "token": token,
                "challenge_id": start["challenge_id"],
                "credential": soft_authenticator(origin=origin).register(start["options"]),
            },
        )
        cookie = done.headers["set-cookie"]
        login = await client.get("/owner/login")
    assert cookie.startswith("__Host-hh_owner=")
    for flag in ("HttpOnly", "Secure", "Path=/", "SameSite=lax"):
        assert flag in cookie
    assert "Domain" not in cookie
    assert "frame-ancestors 'none'" in login.headers["content-security-policy"]
    assert login.headers["x-frame-options"] == "DENY"


# --- the authorization code flow ----------------------------------------------------


async def test_full_flow_with_pkce_reaches_mcp_and_audits_the_client(app, browser, owner):
    tokens = await tokens_for(app, browser)
    assert tokens["token_type"] == "Bearer"
    assert tokens["expires_in"] == 900
    assert tokens["scope"] == "mcp"
    assert tokens["access_token"].startswith("hhat_")
    assert tokens["refresh_token"].startswith("hhrt_")
    async with mcp_client(app, tokens["access_token"]) as client:
        listed = await client.list_tools()
        names = [t.name for t in listed.tools]
        assert names
        await client.call_tool(names[0], {})
    events = await audit_events(app, 20)
    calls = [e for e in events if e.kind == "mcp.tool_call"]
    assert calls[0].actor == "client:cimd:client.example.com:oauth:metadata.json"
    kinds = {e.kind for e in events}
    assert {"oauth.consent_granted", "oauth.grant_created", "owner.passkey_enrolled"} <= kinds


async def test_mcp_exposes_no_approval_tool(app, browser, owner):
    # S2: the model cannot approve. No tool, prompt or resource may approve or claim.
    tokens = await tokens_for(app, browser)
    async with mcp_client(app, tokens["access_token"]) as client:
        listed = await client.list_tools()
    for tool in listed.tools:
        assert not re.search(r"approv|claim|consent|grant", tool.name, re.I)


async def test_consent_needs_a_session_and_csrf_and_deny_is_explicit(app, browser, owner):
    _, challenge = pkce()
    start = await browser.get("/oauth/authorize", params=authorize_params(challenge))
    location = start.headers["location"]
    async with http(app) as anonymous:
        redirect = await anonymous.get(location)
    assert redirect.status_code == 303
    assert redirect.headers["location"].startswith("/owner/login?next=%2Foauth%2Fconsent")
    page = await browser.get(location)
    assert "Example MCP Client" in page.text
    assert "this computer" in page.text  # the loopback warning
    assert "127.0.0.1" in page.text
    request_id = query(location)["request"]
    no_csrf = await browser.post(
        "/oauth/consent", data={"request": request_id, "decision": "approve"}
    )
    assert no_csrf.status_code == 403
    async with http(app, Origin="https://evil.example", Cookie=browser.headers["Cookie"]) as evil:
        forged = await evil.post("/oauth/consent", data={"request": request_id})
    assert forged.status_code == 403
    denied = await consent(browser, location, decision="")  # anything but approve denies
    answer = query(denied.headers["location"])
    assert answer["error"] == "access_denied"
    assert answer["iss"] == ORIGIN
    assert "code" not in answer
    used = await browser.get(location)
    assert used.status_code == 410


@pytest.mark.parametrize(
    ("override", "error"),
    [
        ({"code_challenge": None}, "invalid_request"),
        ({"code_challenge_method": "plain"}, "invalid_request"),
        ({"code_challenge": "short"}, "invalid_request"),
        ({"resource": "https://other.example/mcp"}, "invalid_target"),
        ({"scope": "admin"}, "invalid_scope"),
    ],
)
async def test_authorization_request_refusals(app, browser, owner, override, error):
    _, challenge = pkce()
    response = await browser.get("/oauth/authorize", params=authorize_params(challenge, **override))
    assert response.status_code == 302
    assert query(response.headers["location"])["error"] == error


async def test_unregistered_redirect_uri_is_never_redirected_to(app, browser, owner):
    _, challenge = pkce()
    params = authorize_params(challenge, redirect_uri="https://evil.example/cb")
    response = await browser.get("/oauth/authorize", params=params)
    assert response.status_code == 400
    assert "location" not in response.headers


async def test_pkce_and_code_failures_at_the_token_endpoint(app, browser, owner):
    code, verifier = await get_code(browser)
    async with http(app) as client:
        wrong = await exchange(client, code, "x" * 50)
        assert wrong.json()["error"] == "invalid_grant"
        other = await exchange(client, code, verifier, resource="https://other.example/mcp")
        assert other.json()["error"] == "invalid_target"
        moved = await exchange(client, code, verifier, redirect_uri="http://127.0.0.1:1/x")
        assert moved.json()["error"] == "invalid_request"
        first = await exchange(client, code, verifier)
        assert first.status_code == 200
        access = first.json()["access_token"]
        assert (await mcp_status(app, access)).status_code == 200
        # A replayed code is refused, and the grant it produced is revoked.
        again = await exchange(client, code, verifier)
        assert again.json()["error"] == "invalid_grant"
    assert (await mcp_status(app, access)).status_code == 401


async def test_expired_code_is_refused(app, browser, owner):
    code, verifier = await get_code(browser)
    async with app.state.db_sessions.begin() as session:
        await session.execute(
            text("UPDATE oauth_authorization_codes SET expires_at = now() - interval '1 second'")
        )
    async with http(app) as client:
        assert (await exchange(client, code, verifier)).json()["error"] == "invalid_grant"


async def test_refresh_rotates_and_reuse_revokes_the_family(app, browser, owner):
    first = await tokens_for(app, browser)
    async with http(app) as client:
        second = await refresh(client, first["refresh_token"])
        assert second.status_code == 200, second.text
        second = second.json()
        assert second["refresh_token"] != first["refresh_token"]
        assert (await mcp_status(app, second["access_token"])).status_code == 200
        # The rotated token comes back: someone holds a copy. End the whole family.
        reused = await refresh(client, first["refresh_token"])
        assert reused.json()["error"] == "invalid_grant"
        assert (await refresh(client, second["refresh_token"])).json()["error"] == "invalid_grant"
    assert (await mcp_status(app, second["access_token"])).status_code == 401
    async with app.state.db_sessions() as session:
        reasons = list(await session.scalars(select(OAuthGrant.revoke_reason)))
    assert reasons == ["refresh_reuse"]


async def test_refresh_token_of_another_client_is_refused(app, browser, owner):
    tokens = await tokens_for(app, browser)
    async with http(app) as client:
        registered = await client.post(
            "/oauth/register", json={"redirect_uris": [REDIRECT], "client_name": "Other"}
        )
        other = registered.json()["client_id"]
        response = await refresh(client, tokens["refresh_token"], client_id=other)
    assert response.json()["error"] == "invalid_grant"


async def test_expired_wrong_audience_and_revoked_access_tokens_get_401(app, browser, owner):
    tokens = await tokens_for(app, browser)
    access = tokens["access_token"]
    assert (await mcp_status(app, access)).status_code == 200
    async with app.state.db_sessions.begin() as session:
        await session.execute(update(OAuthGrant).values(resource="https://other.example/mcp"))
    assert (await mcp_status(app, access)).status_code == 401
    async with app.state.db_sessions.begin() as session:
        await session.execute(update(OAuthGrant).values(resource=RESOURCE))
        await session.execute(
            update(OAuthToken)
            .where(OAuthToken.kind == "access")
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    expired = await mcp_status(app, access)
    assert expired.status_code == 401
    assert "resource_metadata=" in expired.headers["www-authenticate"]

    # Per-client revocation through the owner API (hh clients revoke).
    fresh = await refresh(http(app), tokens["refresh_token"])
    access = fresh.json()["access_token"]
    assert (await mcp_status(app, access)).status_code == 200
    async with app.state.db_sessions.begin() as session:
        owner_token = await create_client(session, client_id="hh", role=ClientRole.OWNER)
    async with http(app, Authorization=f"Bearer {owner_token}") as api:
        listed = (await api.get("/api/clients")).json()["clients"]
        oauth = next(c for c in listed if c["kind"] == "oauth-cimd")
        assert oauth["active"] == 1
        assert oauth["name"] == "Example MCP Client"
        revoked = await api.post(f"/api/clients/{oauth['id']}/revoke")
        assert revoked.json() == {"id": oauth["id"], "revoked": 1}
        assert (await api.post("/api/clients/nope/revoke")).status_code == 404
    assert (await mcp_status(app, access)).status_code == 401
    async with http(app) as client:
        assert (await refresh(client, fresh.json()["refresh_token"])).status_code == 400


async def test_revocation_endpoint_ends_the_grant(app, browser, owner):
    tokens = await tokens_for(app, browser)
    async with http(app) as client:
        response = await client.post(
            "/oauth/revoke", data={"token": tokens["access_token"], "client_id": CLIENT}
        )
    assert response.status_code == 200
    assert (await mcp_status(app, tokens["access_token"])).status_code == 401


# --- dynamic client registration ---------------------------------------------------


async def test_dcr_registers_public_clients_that_still_need_consent(app, browser, owner):
    async with http(app) as client:
        registered = await client.post(
            "/oauth/register",
            json={
                "redirect_uris": [REDIRECT],
                "client_name": "Old Client",
                "token_endpoint_auth_method": "client_secret_post",
            },
        )
        assert registered.status_code == 201
        info = registered.json()
        assert info["client_id"].startswith("dcr:")
        assert info["token_endpoint_auth_method"] == "none"
        assert "client_secret" not in info
        refused = await client.post(
            "/oauth/register", json={"redirect_uris": ["http://evil.example/cb"]}
        )
        assert refused.status_code == 400
    verifier, challenge = pkce()
    params = authorize_params(challenge, client_id=info["client_id"])
    start = await browser.get("/oauth/authorize", params=params)
    page = await browser.get(start.headers["location"])
    assert "self-declared" in page.text
    code, verifier = await get_code(browser, client_id=info["client_id"])
    async with http(app) as client:
        tokens = await exchange(client, code, verifier, client_id=info["client_id"])
    assert tokens.status_code == 200
    async with mcp_client(app, tokens.json()["access_token"]) as session:
        listed = await session.list_tools()
        await session.call_tool(listed.tools[0].name, {})
    events = await audit_events(app, 5)
    assert (
        next(e for e in events if e.kind == "mcp.tool_call").actor == f"client:{info['client_id']}"
    )


async def test_dcr_is_rate_limited(app):
    async with http(app) as client:
        statuses = [
            (await client.post("/oauth/register", json={"redirect_uris": [REDIRECT]})).status_code
            for _ in range(6)
        ]
    assert statuses == [201] * 5 + [429]


async def test_login_is_rate_limited(app, owner):
    app.state.auth = dataclasses.replace(app.state.auth, limiter=RateLimiter(DEFAULT_LIMITS))
    async with http(app, Origin=ORIGIN) as client:
        statuses = [
            (
                await client.post("/owner/login/recovery", data={"code": "AAAA-AAAA-AAAA-AAAA"})
            ).status_code
            for _ in range(11)
        ]
    assert statuses[-1] == 429
    assert set(statuses[:10]) == {401}


async def test_dcr_can_be_turned_off(fresh_migrated_url, serve_app):
    application = make_app(fresh_migrated_url, oauth_dcr_enabled=False)
    async with serve_app(application), http(application) as client:
        meta = (await client.get("/.well-known/oauth-authorization-server")).json()
        response = await client.post("/oauth/register", json={"redirect_uris": [REDIRECT]})
    assert "registration_endpoint" not in meta
    assert response.status_code in (404, 405)


async def test_unreachable_metadata_document_refuses_the_client(app, browser, owner, cimd):
    cimd.get("https://93.184.215.14/oauth/other.json").mock(return_value=httpx.Response(500))
    _, challenge = pkce()
    other = "https://client.example.com/oauth/other.json"
    response = await browser.get(
        "/oauth/authorize", params=authorize_params(challenge, client_id=other)
    )
    assert response.status_code == 400
    assert "location" not in response.headers


# --- legacy tokens ------------------------------------------------------------------


async def test_legacy_tokens_follow_the_setting(fresh_migrated_url, serve_app):
    on = make_app(fresh_migrated_url)
    async with serve_app(on):
        async with on.state.db_sessions.begin() as session:
            legacy = await create_client(session, client_id=f"t-{uuid.uuid4().hex[:6]}")
        assert (await mcp_status(on, legacy)).status_code == 200
    off = make_app(fresh_migrated_url, mcp_legacy_tokens=False)
    async with serve_app(off):
        assert (await mcp_status(off, legacy)).status_code == 401
    with pytest.raises(InvalidInput, match="HH_PUBLIC_URL"):
        create_app(Settings(env=Environment.TEST, public_url=None, mcp_legacy_tokens=False))


# --- the SDK's own OAuth client --------------------------------------------------


class _Storage:
    def __init__(self):
        self.tokens = None
        self.client_info = None

    async def get_tokens(self):
        return self.tokens

    async def set_tokens(self, tokens):
        self.tokens = tokens

    async def get_client_info(self):
        return self.client_info

    async def set_client_info(self, client_info):
        self.client_info = client_info


async def test_the_mcp_sdk_oauth_client_completes_the_flow(app, browser, owner):
    """The SDK client discovers, uses CIMD, sends PKCE and resource, validates iss."""
    answers = {}

    async def redirect_handler(url):
        # The "browser": the owner is signed in and approves.
        start = await browser.get(url.removeprefix(ORIGIN))
        decided = await consent(browser, start.headers["location"])
        answers.update(query(decided.headers["location"]))

    async def callback_handler():
        return AuthorizationCodeResult(
            code=answers["code"], state=answers.get("state"), iss=answers.get("iss")
        )

    storage = _Storage()
    auth = OAuthClientProvider(
        server_url=RESOURCE,
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl(REDIRECT)], client_name="Example MCP Client"
        ),
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
        client_metadata_url=CLIENT,
    )
    client = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=ORIGIN, auth=auth)
    transport = streamable_http_client(RESOURCE, http_client=client)
    async with Client(transport, mode="auto", cache=None) as session:
        listed = await session.list_tools()
    assert listed.tools
    assert storage.tokens.access_token.startswith("hhat_")
    assert storage.client_info.client_id == CLIENT


# --- logs carry no secrets ---------------------------------------------------------


async def test_no_token_code_or_cookie_reaches_the_logs(app, browser, passkey, capsys):
    configure_logging(Settings(env=Environment.TEST, log_level="DEBUG", log_format=LogFormat.JSON))
    try:
        enrollment, enroll_token = await enroll(app, browser, passkey)
        cookie = browser.headers["Cookie"].split("=", 1)[1]
        code, verifier = await get_code(browser)
        async with http(app) as client:
            tokens = (await exchange(client, code, verifier)).json()
            rotated = (await refresh(client, tokens["refresh_token"])).json()
            await refresh(client, tokens["refresh_token"])  # reuse: logged as a warning
        await mcp_status(app, rotated["access_token"])
        async with http(app, Origin=ORIGIN) as fresh:
            await fresh.post("/owner/login/recovery", data={"code": enrollment.recovery_codes[0]})
        out = capsys.readouterr()
    finally:
        structlog.reset_defaults()
        logging.getLogger().handlers.clear()
    logs = out.out + out.err
    assert "oauth_grant_revoked" in logs  # the logs were captured
    secrets_seen = [
        enroll_token,
        cookie,
        code,
        verifier,
        tokens["access_token"],
        tokens["refresh_token"],
        rotated["access_token"],
        rotated["refresh_token"],
        enrollment.recovery_codes[0],
        enrollment.recovery_codes[0].replace("-", ""),
    ]
    for value in secrets_seen:
        assert value not in logs
