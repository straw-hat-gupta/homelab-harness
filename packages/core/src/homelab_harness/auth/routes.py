"""HTTP routes for owner login, enrollment, consent and the authorization server.

Interface layer. The OAuth protocol endpoints reuse the MCP SDK's handlers
(metadata, authorize, token, revoke) on the harness's own paths; consent, the
owner pages and client registration are the harness's.

Browser-facing state changes are protected twice against cross-site requests:
the ``Origin`` header must be this harness's origin, and consent forms carry a
CSRF token bound to the session. The session cookie is ``HttpOnly``,
``SameSite=Lax`` (an authorization request arrives as a top-level navigation
started by the client, and ``Strict`` could strip the cookie from it) and
``Secure`` with the ``__Host-`` prefix whenever the harness is served over HTTPS.
"""

from __future__ import annotations

import hmac
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib.resources import files
from typing import Any
from urllib.parse import urlencode

import structlog
from fastapi import FastAPI
from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.metadata import MetadataHandler, ProtectedResourceMetadataHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
from mcp.server.auth.routes import cors_middleware
from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from homelab_harness.auth.config import (
    AS_METADATA_PATH,
    AUTHORIZE_PATH,
    CONSENT_PATH,
    ENROLL_PATH,
    LOGIN_PATH,
    PRM_PATH,
    PRM_ROOT_PATH,
    REGISTER_PATH,
    REVOKE_PATH,
    SCOPE,
    TOKEN_PATH,
    AuthConfig,
)
from homelab_harness.auth.dcr import RegistrationEndpoint
from homelab_harness.auth.owner import AuthFailed, OwnerService, csrf_token_for
from homelab_harness.auth.pages import (
    SECURITY_HEADERS,
    STATIC_PREFIX,
    consent_page,
    enroll_page,
    login_page,
    message_page,
)
from homelab_harness.auth.provider import ConsentError, HarnessOAuthProvider, same_resource
from homelab_harness.auth.ratelimit import RateLimiter

log = structlog.get_logger(__name__)

type Endpoint = Callable[[Request], Awaitable[Response]]
type ServicedEndpoint = Callable[[Request, "AuthServices"], Awaitable[Response]]

_STATIC = {"webauthn.js": "text/javascript", "owner.css": "text/css"}
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_MAX_JSON_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True)
class AuthServices:
    """What the auth routes need, built once the database is open."""

    config: AuthConfig
    owner: OwnerService
    provider: HarnessOAuthProvider
    limiter: RateLimiter


def _services(request: Request) -> AuthServices | None:
    return getattr(request.app.state, "auth", None)


def _unavailable() -> Response:
    return JSONResponse(
        {"error": "temporarily_unavailable", "error_description": "the auth database is not ready"},
        status_code=503,
        headers=_NO_STORE,
    )


def _client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _too_many(retry_after: int, *, html: bool) -> Response:
    headers = {"Retry-After": str(retry_after), **_NO_STORE}
    if html:
        page = message_page("Slow down", "Too many attempts; wait a minute and try again.")
        return HTMLResponse(page, status_code=429, headers={**SECURITY_HEADERS, **headers})
    return JSONResponse(
        {"error": "slow_down", "error_description": "too many requests"},
        status_code=429,
        headers=headers,
    )


def _limited(bucket: str, *, html: bool = False) -> Callable[[ServicedEndpoint], Endpoint]:
    """Wrap an endpoint so it is rate-limited and answers 503 before the database is up."""

    def wrap(endpoint: ServicedEndpoint) -> Endpoint:
        async def limited(request: Request) -> Response:
            services = _services(request)
            if services is None:
                return _unavailable()
            decision = services.limiter.check(bucket, _client_address(request))
            if not decision.allowed:
                log.warning("auth_rate_limited", bucket=bucket)
                return _too_many(decision.retry_after_seconds, html=html)
            return await endpoint(request, services)

        return limited

    return wrap


def _serviced(endpoint: ServicedEndpoint) -> Endpoint:
    """Wrap an endpoint so it answers 503 before the database is up."""

    async def serviced(request: Request) -> Response:
        services = _services(request)
        if services is None:
            return _unavailable()
        return await endpoint(request, services)

    return serviced


def _html(body: str, *, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(body, status_code=status_code, headers=SECURITY_HEADERS)


def _same_origin(request: Request, config: AuthConfig) -> bool:
    """Whether a state-changing browser request comes from the harness's own pages."""
    origin = request.headers.get("origin")
    if origin is not None:
        return origin == config.origin
    return request.headers.get("sec-fetch-site") == "same-origin"


def _safe_next(value: str | None) -> str:
    """Only local paths, so ``next`` cannot become an open redirect."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return LOGIN_PATH


def _with_session(response: Response, config: AuthConfig, token: str) -> Response:
    response.set_cookie(
        config.session_cookie,
        token,
        max_age=int(config.session_max.total_seconds()),
        path="/",
        secure=config.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    return response


class _Json(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _EnrollOptions(_Json):
    token: str = Field(max_length=128)


class _EnrollVerify(_Json):
    token: str = Field(max_length=128)
    challenge_id: uuid.UUID
    credential: dict[str, Any]


class _LoginVerify(_Json):
    challenge_id: uuid.UUID
    credential: dict[str, Any]
    next: str | None = Field(default=None, max_length=2048)


async def _json_body[T: BaseModel](request: Request, model: type[T]) -> T | None:
    body = await request.body()
    if len(body) > _MAX_JSON_BYTES:
        return None
    try:
        return model.model_validate_json(body or b"{}")
    except ValidationError:
        return None


def _refused(message: str, *, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status_code, headers=_NO_STORE)


# --- owner pages ---------------------------------------------------------------


@_serviced
async def login_form(request: Request, services: AuthServices) -> Response:
    """``GET /owner/login``."""
    next_path = _safe_next(request.query_params.get("next"))
    cookie = request.cookies.get(services.config.session_cookie)
    if next_path == LOGIN_PATH and await services.owner.session_for(cookie) is not None:
        return _html(message_page("Signed in", "You are signed in to the harness."))
    return _html(login_page(next_path=next_path))


@_limited("login")
async def login_options(request: Request, services: AuthServices) -> Response:
    """``POST /owner/login/options``: start a passkey login."""
    if not _same_origin(request, services.config):
        return _refused("cross-origin request refused", status_code=403)
    try:
        ceremony = await services.owner.login_options()
    except AuthFailed as exc:
        return _refused(str(exc), status_code=409)
    return JSONResponse(
        {"challenge_id": str(ceremony.challenge_id), "options": ceremony.options}, headers=_NO_STORE
    )


@_limited("login")
async def login_verify(request: Request, services: AuthServices) -> Response:
    """``POST /owner/login/verify``: finish a passkey login and set the session cookie."""
    if not _same_origin(request, services.config):
        return _refused("cross-origin request refused", status_code=403)
    body = await _json_body(request, _LoginVerify)
    if body is None:
        return _refused("malformed sign-in request")
    try:
        token = await services.owner.login_with_passkey(
            challenge_id=body.challenge_id, credential=body.credential
        )
    except AuthFailed as exc:
        log.info("owner_login_failed", method="passkey")
        return _refused(str(exc), status_code=401)
    response = JSONResponse({"redirect": _safe_next(body.next)}, headers=_NO_STORE)
    return _with_session(response, services.config, token)


@_limited("login", html=True)
async def login_recovery(request: Request, services: AuthServices) -> Response:
    """``POST /owner/login/recovery``: sign in with a recovery code (form post)."""
    if not _same_origin(request, services.config):
        return _html(message_page("Refused", "Cross-origin request refused."), status_code=403)
    form = await request.form()
    code, nxt = form.get("code"), form.get("next")
    next_path = _safe_next(nxt if isinstance(nxt, str) else None)
    try:
        if not isinstance(code, str) or len(code) > 64:
            raise AuthFailed("that recovery code is not valid")
        token = await services.owner.login_with_recovery_code(code)
    except AuthFailed as exc:
        log.info("owner_login_failed", method="recovery_code")
        return _html(login_page(next_path=next_path, error=str(exc)), status_code=401)
    response = RedirectResponse(next_path, status_code=303, headers=SECURITY_HEADERS)
    return _with_session(response, services.config, token)


@_serviced
async def logout(request: Request, services: AuthServices) -> Response:
    """``POST /owner/logout``."""
    if not _same_origin(request, services.config):
        return _html(message_page("Refused", "Cross-origin request refused."), status_code=403)
    cookie = request.cookies.get(services.config.session_cookie)
    if cookie:
        await services.owner.logout(cookie)
    response = _html(message_page("Signed out", "You are signed out."))
    response.delete_cookie(
        services.config.session_cookie, path="/", secure=services.config.secure_cookies
    )
    return response


@_serviced
async def enroll_form(_request: Request, _services: AuthServices) -> Response:
    """``GET /owner/enroll``: the page reads the one-time token from the fragment."""
    return _html(enroll_page())


@_limited("login")
async def enroll_options(request: Request, services: AuthServices) -> Response:
    """``POST /owner/enroll/options``."""
    if not _same_origin(request, services.config):
        return _refused("cross-origin request refused", status_code=403)
    body = await _json_body(request, _EnrollOptions)
    if body is None:
        return _refused("malformed enrollment request")
    try:
        ceremony = await services.owner.enrollment_options(body.token)
    except AuthFailed as exc:
        return _refused(str(exc), status_code=401)
    return JSONResponse(
        {"challenge_id": str(ceremony.challenge_id), "options": ceremony.options}, headers=_NO_STORE
    )


@_limited("login")
async def enroll_verify(request: Request, services: AuthServices) -> Response:
    """``POST /owner/enroll/verify``: store the passkey and sign the owner in."""
    if not _same_origin(request, services.config):
        return _refused("cross-origin request refused", status_code=403)
    body = await _json_body(request, _EnrollVerify)
    if body is None:
        return _refused("malformed enrollment request")
    try:
        token = await services.owner.complete_enrollment(
            token=body.token, challenge_id=body.challenge_id, credential=body.credential
        )
    except AuthFailed as exc:
        log.info("owner_enrollment_failed")
        return _refused(str(exc), status_code=401)
    response = JSONResponse({"redirect": LOGIN_PATH}, headers=_NO_STORE)
    return _with_session(response, services.config, token)


async def static_file(request: Request) -> Response:
    """``GET /owner/static/{name}``: the page script and stylesheet."""
    name = request.path_params["name"]
    if name not in _STATIC:
        return Response(status_code=404)
    body = (files("homelab_harness.auth") / "static" / name).read_bytes()
    return Response(
        body,
        media_type=_STATIC[name],
        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
    )


# --- consent -------------------------------------------------------------------


def _request_id(value: object) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


@_serviced
async def consent_form(request: Request, services: AuthServices) -> Response:
    """``GET /oauth/consent?request=…``: needs an owner session, else sends to login."""
    cookie = request.cookies.get(services.config.session_cookie)
    if cookie is None or await services.owner.session_for(cookie) is None:
        target = f"{CONSENT_PATH}?{request.url.query}"
        return RedirectResponse(
            f"{LOGIN_PATH}?{urlencode({'next': target})}", status_code=303, headers=SECURITY_HEADERS
        )
    request_id = _request_id(request.query_params.get("request"))
    if request_id is None:
        return _html(message_page("Not found", "Unknown authorization request."), status_code=404)
    try:
        pending = await services.provider.pending(request_id)
    except ConsentError as exc:
        return _html(message_page("Expired", str(exc)), status_code=410)
    minutes = int(services.config.access_token_ttl.total_seconds() // 60)
    return _html(consent_page(pending, csrf=csrf_token_for(cookie), access_minutes=minutes))


@_serviced
async def consent_decision(request: Request, services: AuthServices) -> Response:
    """``POST /oauth/consent``: the owner's answer; anything but an explicit approve denies."""
    if not _same_origin(request, services.config):
        return _html(message_page("Refused", "Cross-origin request refused."), status_code=403)
    cookie = request.cookies.get(services.config.session_cookie)
    if cookie is None or await services.owner.session_for(cookie) is None:
        return _html(message_page("Signed out", "Sign in again and retry."), status_code=401)
    form = await request.form()
    csrf = form.get("csrf")
    if not isinstance(csrf, str) or not _equal(csrf, csrf_token_for(cookie)):
        return _html(message_page("Refused", "The form expired; start again."), status_code=403)
    request_id = _request_id(form.get("request"))
    if request_id is None:
        return _html(message_page("Not found", "Unknown authorization request."), status_code=404)
    try:
        location = await services.provider.decide(
            request_id, approve=form.get("decision") == "approve"
        )
    except ConsentError as exc:
        return _html(message_page("Expired", str(exc)), status_code=410)
    return RedirectResponse(location, status_code=303, headers=SECURITY_HEADERS)


def _equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# --- OAuth protocol endpoints (SDK handlers) -----------------------------------


def authorization_server_metadata(config: AuthConfig) -> OAuthMetadata:
    """RFC 8414 metadata for this authorization server."""
    data: dict[str, Any] = {
        "issuer": config.issuer,
        "authorization_endpoint": config.url(AUTHORIZE_PATH),
        "token_endpoint": config.url(TOKEN_PATH),
        "revocation_endpoint": config.url(REVOKE_PATH),
        "revocation_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [SCOPE],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "client_id_metadata_document_supported": True,
        "authorization_response_iss_parameter_supported": True,
    }
    if config.dcr_enabled:
        data["registration_endpoint"] = config.url(REGISTER_PATH)
    return OAuthMetadata.model_validate(data)


def protected_resource_metadata(config: AuthConfig) -> ProtectedResourceMetadata:
    """RFC 9728 metadata for ``/mcp``."""
    return ProtectedResourceMetadata.model_validate(
        {
            "resource": config.resource,
            "authorization_servers": [config.issuer],
            "scopes_supported": [SCOPE],
            "bearer_methods_supported": ["header"],
            "resource_name": "homelab-harness",
        }
    )


@_limited("authorize")
async def authorize(request: Request, services: AuthServices) -> Response:
    """``GET|POST /oauth/authorize`` through the SDK handler (PKCE S256 required)."""
    return await AuthorizationHandler(services.provider).handle(request)


@_limited("token")
async def token(request: Request, services: AuthServices) -> Response:
    """``POST /oauth/token``: authorization_code (with PKCE) and refresh_token grants."""
    form = await request.form()  # cached on the request; the SDK handler reads it again
    resource = form.get("resource")
    if isinstance(resource, str) and not same_resource(resource, services.config.resource):
        return JSONResponse(
            {"error": "invalid_target", "error_description": "unknown resource"},
            status_code=400,
            headers=_NO_STORE,
        )
    handler = TokenHandler(services.provider, ClientAuthenticator(services.provider))
    return await handler.handle(request)


@_limited("token")
async def revoke(request: Request, services: AuthServices) -> Response:
    """``POST /oauth/revoke`` (RFC 7009): revoking either token ends its grant.

    Not the SDK's handler: its request model requires ``client_secret``, which
    public clients (all of the harness's) never send.
    """
    try:
        client = await ClientAuthenticator(services.provider).authenticate_request(request)
    except AuthenticationError:
        return JSONResponse({"error": "invalid_client"}, status_code=401, headers=_NO_STORE)
    form = await request.form()
    token = form.get("token")
    if not isinstance(token, str) or not token:
        return JSONResponse({"error": "invalid_request"}, status_code=400, headers=_NO_STORE)
    provider = services.provider
    found = await provider.load_access_token(token) or await provider.load_refresh_token(
        client, token
    )
    # RFC 7009 §2.2: unknown tokens, and other clients' tokens, still get 200.
    if found is not None and found.client_id == client.client_id:
        await provider.revoke_token(found)
    return Response(status_code=200, headers=_NO_STORE)


@_limited("register")
async def register(request: Request, services: AuthServices) -> Response:
    """``POST /oauth/register``: dynamic client registration of public clients."""
    return await RegistrationEndpoint(services.provider)(request)


def install_auth_routes(app: FastAPI, config: AuthConfig) -> None:
    """Route the owner pages, consent and the OAuth endpoints on ``app``.

    The endpoints answer 503 until ``app.state.auth`` is set at startup.
    """
    as_metadata = MetadataHandler(authorization_server_metadata(config)).handle
    prm = ProtectedResourceMetadataHandler(protected_resource_metadata(config)).handle
    get, post, cors_get = ["GET"], ["POST"], ["GET", "OPTIONS"]
    routes = [
        Route(LOGIN_PATH, login_form, methods=get),
        Route(f"{LOGIN_PATH}/options", login_options, methods=post),
        Route(f"{LOGIN_PATH}/verify", login_verify, methods=post),
        Route(f"{LOGIN_PATH}/recovery", login_recovery, methods=post),
        Route("/owner/logout", logout, methods=post),
        Route(ENROLL_PATH, enroll_form, methods=get),
        Route(f"{ENROLL_PATH}/options", enroll_options, methods=post),
        Route(f"{ENROLL_PATH}/verify", enroll_verify, methods=post),
        Route(STATIC_PREFIX + "/{name}", static_file, methods=get),
        Route(CONSENT_PATH, consent_form, methods=get),
        Route(CONSENT_PATH, consent_decision, methods=post),
        Route(AS_METADATA_PATH, cors_middleware(as_metadata, cors_get), methods=cors_get),
        Route(PRM_PATH, cors_middleware(prm, cors_get), methods=cors_get),
        Route(PRM_ROOT_PATH, cors_middleware(prm, cors_get), methods=cors_get),
        Route(AUTHORIZE_PATH, authorize, methods=["GET", "POST"]),
        Route(TOKEN_PATH, cors_middleware(token, ["POST", "OPTIONS"]), methods=["POST", "OPTIONS"]),
        Route(
            REVOKE_PATH, cors_middleware(revoke, ["POST", "OPTIONS"]), methods=["POST", "OPTIONS"]
        ),
    ]
    if config.dcr_enabled:
        routes.append(
            Route(
                REGISTER_PATH,
                cors_middleware(register, ["POST", "OPTIONS"]),
                methods=["POST", "OPTIONS"],
            )
        )
    app.router.routes.extend(routes)
