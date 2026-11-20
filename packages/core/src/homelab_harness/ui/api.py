"""The web UI's read-only REST façade under ``/api/ui`` (interim).

Interface layer: each route checks the owner token, calls the
:class:`~homelab_harness.ui.service.UiReadService`, and shapes errors. The
Stage 2 lab state will back these routes; until then they read through the
Proxmox read tools. Owner-only, with the same interim owner bearer token as
the vault API, until the passkey session lands (ADR-0007).
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from homelab_harness.owner_auth import require_owner
from homelab_harness.ui.service import UiReadService, UiUnavailable
from homelab_harness.ui.views import ObjectSummary, ObjectType, TreeResponse
from homelab_harness_sdk.errors import (
    AuthRejected,
    HarnessError,
    InvalidInput,
    NotFound,
    PermissionDenied,
    RateLimited,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/ui", tags=["ui"])

Owner = Annotated[str, Depends(require_owner)]

# Errors from the target side (unreachable, refused credential, anything else)
# are a bad gateway: the harness is up, the cluster is not answering usefully.
_STATUS: tuple[tuple[type[HarnessError], int], ...] = (
    (InvalidInput, status.HTTP_400_BAD_REQUEST),
    (PermissionDenied, status.HTTP_403_FORBIDDEN),
    (NotFound, status.HTTP_404_NOT_FOUND),
    (RateLimited, status.HTTP_429_TOO_MANY_REQUESTS),
    (AuthRejected, status.HTTP_502_BAD_GATEWAY),
)


def _service(request: Request) -> UiReadService:
    service: UiReadService = request.app.state.ui_service
    return service


Service = Annotated[UiReadService, Depends(_service)]


def _http_error(exc: Exception, *, view: str) -> HTTPException:
    """Map a façade failure to an owner-safe HTTP error (no target bodies, no traces)."""
    if isinstance(exc, HarnessError):
        code = next((c for t, c in _STATUS if isinstance(exc, t)), status.HTTP_502_BAD_GATEWAY)
        return HTTPException(code, detail=exc.safe_message)
    if isinstance(exc, UiUnavailable):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    log.error("ui_read_crashed", view=view, error_type=type(exc).__name__)
    return HTTPException(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="the UI read failed inside the harness; the owner can find it in the logs",
    )


@router.get("/tree")
async def tree(service: Service, client_id: Owner) -> TreeResponse:
    """Every registered cluster with its nodes, guests and storages (the side tree).

    Interim: read live through ``proxmox.cluster.resources``; the lab state
    will serve it in Stage 2.
    """
    try:
        return await service.tree(client_id=client_id)
    except Exception as exc:  # boundary: shape every failure for the owner
        raise _http_error(exc, view="tree") from None


@router.get("/objects/{object_type}/{object_id}/summary")
async def summary(
    object_type: ObjectType, object_id: str, service: Service, client_id: Owner
) -> ObjectSummary:
    """What an object's Summary tab shows: stats, properties and child objects.

    Interim: read live through the matching Proxmox read tool; the lab state
    will serve it in Stage 2.
    """
    try:
        return await service.summary(
            client_id=client_id, object_type=object_type, object_id=object_id
        )
    except Exception as exc:  # boundary: shape every failure for the owner
        raise _http_error(exc, view="summary") from None
