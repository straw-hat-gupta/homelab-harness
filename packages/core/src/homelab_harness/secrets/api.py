"""The owner's vault API under ``/api`` (used by ``hh secret`` and ``hh vault``).

Interface layer: routes parse input, call the vault service, and shape the
response. Every route requires an owner token
(:func:`homelab_harness.owner_auth.require_owner`).

No route returns a secret value, length or hash: responses are built from
:class:`~homelab_harness.secrets.service.SecretInfo`, which has none. There is
no reveal route. Creating and rotating accept the value in the request body
(over the tailnet); it is validated by the kind models, wrapped at once, and
never logged.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from homelab_harness.owner_auth import require_owner
from homelab_harness.secrets.crypto import SecretIntegrityError
from homelab_harness.secrets.keys import KeyProviderError
from homelab_harness.secrets.kinds import SecretKind
from homelab_harness.secrets.payloads import (
    GENERATED_KINDS,
    authorized_keys_line,
    check_from_hosts,
    generate_ssh_key,
    parse_fields,
)
from homelab_harness.secrets.service import SecretInfo, VaultService
from homelab_harness_sdk.errors import Conflict, HarnessError, InvalidInput, NotFound

log = structlog.get_logger(__name__)

_OWNER = "owner"

router = APIRouter(prefix="/api", tags=["vault"], dependencies=[Depends(require_owner)])


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CreateSecretRequest(_Request):
    """Body of ``POST /api/secrets``. Exactly one of ``value`` and ``fields``."""

    name: str
    kind: SecretKind
    value: str | None = None
    fields: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict[str, Any])
    description: str = ""
    tags: list[str] = Field(default_factory=list[str])
    expires_at: AwareDatetime | None = None
    rotate_every_seconds: int | None = Field(default=None, ge=1)


class RotateSecretRequest(_Request):
    """Body of ``POST /api/secrets/{name}/versions``: a new value, or ``generate``."""

    value: str | None = None
    fields: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    generate: bool = False


class GenerateSecretRequest(_Request):
    """Body of ``POST /api/secrets/generate``."""

    name: str
    kind: Literal["ssh_key"] = "ssh_key"
    comment: str = ""
    from_hosts: list[str] = Field(default_factory=list[str])
    description: str = ""
    tags: list[str] = Field(default_factory=list[str])
    expires_at: AwareDatetime | None = None
    rotate_every_seconds: int | None = Field(default=None, ge=1)


class VersionResponse(BaseModel):
    """One stored version."""

    version: int
    kek_id: str
    created_at: datetime


class SecretResponse(BaseModel):
    """A secret's plain description."""

    id: str
    name: str
    handle: str
    kind: SecretKind
    description: str
    tags: list[str]
    source: str
    metadata: dict[str, Any]
    created_at: datetime
    rotated_at: datetime | None
    expires_at: datetime | None
    rotate_every_seconds: int | None
    revoked_at: datetime | None
    current_version: int
    versions: list[VersionResponse]

    @classmethod
    def of(cls, info: SecretInfo) -> SecretResponse:
        """Shape a service description for the API."""
        return cls(
            id=str(info.id),
            name=info.name,
            handle=f"secret://{info.name}",
            kind=info.kind,
            description=info.description,
            tags=list(info.tags),
            source=info.source,
            metadata=dict(info.metadata),
            created_at=info.created_at,
            rotated_at=info.rotated_at,
            expires_at=info.expires_at,
            rotate_every_seconds=(
                int(info.rotate_every.total_seconds()) if info.rotate_every else None
            ),
            revoked_at=info.revoked_at,
            current_version=info.current_version,
            versions=[
                VersionResponse(version=v.version, kek_id=v.kek_id, created_at=v.created_at)
                for v in info.versions
            ],
        )


class SecretListResponse(BaseModel):
    """``GET /api/secrets``."""

    secrets: list[SecretResponse]


class GeneratedKeyResponse(BaseModel):
    """A generated SSH key: only its public half."""

    secret: SecretResponse
    public_key: str
    authorized_keys: str


class DeleteResponse(BaseModel):
    """``DELETE /api/secrets/{name}``."""

    name: str
    versions_destroyed: int


class RewrapResponse(BaseModel):
    """``POST /api/vault/rotate-kek``."""

    kek_id: str
    rewrapped: int
    already_current: int
    failed: int


def _vault(request: Request) -> VaultService:
    vault: VaultService | None = getattr(request.app.state, "vault", None)
    if vault is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="the vault is off: it needs HH_DATABASE_URL and HH_SECRETS_KEK_PROVIDER",
        )
    return vault


Vault = Annotated[VaultService, Depends(_vault)]

_STATUS: tuple[tuple[type[HarnessError], int], ...] = (
    (InvalidInput, status.HTTP_400_BAD_REQUEST),
    (NotFound, status.HTTP_404_NOT_FOUND),
    (Conflict, status.HTTP_409_CONFLICT),
)


@contextmanager
def _owner_errors(action: str) -> Generator[None]:
    """Turn service errors into owner-safe HTTP errors."""
    try:
        yield
    except HarnessError as exc:
        code = next((c for t, c in _STATUS if isinstance(exc, t)), status.HTTP_502_BAD_GATEWAY)
        raise HTTPException(code, detail=exc.safe_message) from None
    except (KeyProviderError, SecretIntegrityError) as exc:
        log.error("vault_operation_failed", action=action, error_type=type(exc).__name__)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"the vault could not {action}; the owner can find the reason in the logs",
        ) from None


def _interval(seconds: int | None) -> timedelta | None:
    return timedelta(seconds=seconds) if seconds is not None else None


@router.get("/secrets")
async def list_secrets(vault: Vault) -> SecretListResponse:
    """List every secret's metadata."""
    return SecretListResponse(secrets=[SecretResponse.of(i) for i in await vault.list_secrets()])


@router.post("/secrets", status_code=status.HTTP_201_CREATED)
async def create_secret(body: CreateSecretRequest, vault: Vault) -> SecretResponse:
    """Store a new secret; the response holds metadata only."""
    with _owner_errors("store the secret"):
        fields = parse_fields(body.kind, value=body.value, fields=body.fields)
        info = await vault.create(
            name=body.name,
            fields=fields,
            metadata=body.metadata,
            actor=_OWNER,
            description=body.description,
            tags=body.tags,
            expires_at=body.expires_at,
            rotate_every=_interval(body.rotate_every_seconds),
        )
    return SecretResponse.of(info)


@router.post("/secrets/generate", status_code=status.HTTP_201_CREATED)
async def generate_secret(body: GenerateSecretRequest, vault: Vault) -> GeneratedKeyResponse:
    """Generate an ed25519 key inside the harness; return only the public key."""
    with _owner_errors("store the generated key"):
        check_from_hosts(body.from_hosts)
        info = await vault.create(
            name=body.name,
            fields=generate_ssh_key(),
            metadata={"comment": body.comment},
            actor=_OWNER,
            description=body.description,
            tags=body.tags,
            expires_at=body.expires_at,
            rotate_every=_interval(body.rotate_every_seconds),
        )
        public_key = str(info.metadata["public_key"])
        line = authorized_keys_line(public_key, from_hosts=body.from_hosts)
    return GeneratedKeyResponse(
        secret=SecretResponse.of(info), public_key=public_key, authorized_keys=line
    )


@router.get("/secrets/{name}")
async def show_secret(name: str, vault: Vault) -> SecretResponse:
    """One secret's metadata and versions."""
    with _owner_errors("describe the secret"):
        info = await vault.get_metadata(name=name)
    return SecretResponse.of(info)


@router.post("/secrets/{name}/versions")
async def rotate_secret(name: str, body: RotateSecretRequest, vault: Vault) -> SecretResponse:
    """Store a new version: a new value, or a regenerated key for generated kinds."""
    with _owner_errors("rotate the secret"):
        kind = (await vault.get_metadata(name=name)).kind
        if body.generate:
            if kind not in GENERATED_KINDS or body.value is not None or body.fields is not None:
                raise InvalidInput(f"'generate' is only for {sorted(GENERATED_KINDS)}, alone")
            fields = generate_ssh_key()
        else:
            fields = parse_fields(kind, value=body.value, fields=body.fields)
        info = await vault.add_version(
            name=name, fields=fields, actor=_OWNER, metadata=body.metadata
        )
    return SecretResponse.of(info)


@router.post("/secrets/{name}/revoke")
async def revoke_secret(name: str, vault: Vault) -> SecretResponse:
    """Make a secret unusable until it is rotated."""
    with _owner_errors("revoke the secret"):
        info = await vault.revoke(name=name, actor=_OWNER)
    return SecretResponse.of(info)


@router.delete("/secrets/{name}")
async def delete_secret(
    name: str, vault: Vault, confirm: Annotated[str, Query(max_length=128)] = ""
) -> DeleteResponse:
    """Crypto-shred a secret; ``confirm`` must repeat its name."""
    with _owner_errors("delete the secret"):
        destroyed = await vault.delete(name=name, confirm_name=confirm, actor=_OWNER)
    return DeleteResponse(name=name, versions_destroyed=destroyed)


@router.post("/vault/rotate-kek")
async def rotate_kek(vault: Vault) -> RewrapResponse:
    """Rewrap every data key under the current KEK."""
    with _owner_errors("rewrap the data keys"):
        report = await vault.rewrap_all(actor=_OWNER)
    return RewrapResponse(
        kek_id=report.kek_id,
        rewrapped=report.rewrapped,
        already_current=report.already_current,
        failed=report.failed,
    )
