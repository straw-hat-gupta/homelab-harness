"""Dynamic Client Registration (RFC 7591) at ``/oauth/register``: the deprecated fallback.

The SDK's registration handler mints a client secret for any client that does
not ask for ``none``, and the SDK compares secrets in plain text, so the
harness would have to store them. It registers public clients only instead
(PKCE protects their codes), replacing a requested secret-based method with
``none`` as RFC 7591 §3.2.1 allows. A registration grants nothing by itself:
every authorization still needs the owner's consent, and the consent screen
says the client's name is self-declared.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from mcp.server.auth.json_response import PydanticJSONResponse
from mcp.shared.auth import JWT_BEARER_GRANT_TYPE, OAuthClientInformationFull, OAuthClientMetadata
from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import Response

from homelab_harness.auth.client_rules import (
    MAX_REDIRECT_URIS,
    check_redirect_uri,
    clean_client_name,
)
from homelab_harness.auth.config import SCOPE
from homelab_harness.auth.provider import DCR_PREFIX, HarnessOAuthProvider

MAX_BODY_BYTES = 8 * 1024


class _RegistrationError(BaseModel):
    error: str
    error_description: str


def _refuse(description: str, *, status_code: int = 400) -> Response:
    return PydanticJSONResponse(
        content=_RegistrationError(error="invalid_client_metadata", error_description=description),
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


class RegistrationEndpoint:
    """``POST /oauth/register``."""

    def __init__(self, provider: HarnessOAuthProvider) -> None:
        """Create the endpoint over the provider that stores clients."""
        self._provider = provider

    async def __call__(self, request: Request) -> Response:
        """Validate the metadata and register a public client."""
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return _refuse("registration request is too large", status_code=413)
        try:
            metadata = OAuthClientMetadata.model_validate_json(body)
        except ValidationError:
            return _refuse("registration metadata is not valid")
        uris = [str(u) for u in metadata.redirect_uris or []]
        if not uris or len(uris) > MAX_REDIRECT_URIS:
            return _refuse(f"between 1 and {MAX_REDIRECT_URIS} redirect_uris are required")
        for uri in uris:
            problem = check_redirect_uri(uri)
            if problem is not None:
                return _refuse(problem)
        if "authorization_code" not in metadata.grant_types:
            return _refuse("grant_types must include authorization_code")
        if JWT_BEARER_GRANT_TYPE in metadata.grant_types:
            return _refuse("the jwt-bearer grant is not supported")
        if "code" not in metadata.response_types:
            return _refuse("response_types must include code")
        if metadata.scope is not None and set(metadata.scope.split()) - {SCOPE}:
            return _refuse(f"the only scope is {SCOPE!r}")
        client_id = DCR_PREFIX + secrets.token_hex(12)
        info: dict[str, Any] = {
            "client_id": client_id,
            "client_id_issued_at": int(time.time()),
            "client_name": clean_client_name(metadata.client_name or "", fallback=client_id),
            "redirect_uris": uris,
            "token_endpoint_auth_method": "none",
            "grant_types": [
                g for g in metadata.grant_types if g in ("authorization_code", "refresh_token")
            ],
            "response_types": ["code"],
            "scope": SCOPE,
        }
        client = OAuthClientInformationFull.model_validate(info)
        await self._provider.register_client(client)
        return PydanticJSONResponse(
            content=client, status_code=201, headers={"Cache-Control": "no-store"}
        )
