"""Map Proxmox HTTP failures to the shared SDK error types.

PVE reports most failures as HTTP 500 with the reason in the status line and in
the body's ``message``/``errors``. That text is used to *classify* the failure
(a lock, a missing object) and is then discarded: it is target-sourced, can
quote config values, and never goes into ``safe_message`` (S7, R-16).

Pure logic: no I/O, no framework imports.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, cast

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

_LOCKED = re.compile(r"can't lock file|\bis locked\b|\blocked\b", re.IGNORECASE)
_MISSING = re.compile(r"does not exist|\bno such\b", re.IGNORECASE)
_EXISTS = re.compile(r"already exists", re.IGNORECASE)

# pveproxy answers 595 when it cannot reach the node it proxies to.
PVE_NODE_UNREACHABLE = 595


class TlsVerificationFailed(TargetUnavailable):
    """The target's certificate did not match the CA bundle or pinned fingerprint.

    Never retried: a mismatch is either a re-issued certificate (the owner
    re-pins) or an interception attempt, and neither resolves by waiting.
    """

    retryable = False


class UnexpectedResponse(HarnessError):
    """The target answered 2xx with a body the adapter could not parse."""


def _reason_text(reason: str, body: Any) -> str:
    parts = [reason]
    if isinstance(body, dict):
        fields = cast(dict[str, Any], body)
        message = fields.get("message")
        if isinstance(message, str):
            parts.append(message)
        errors = fields.get("errors")
        if isinstance(errors, dict):
            parts.extend(str(v) for v in cast(dict[str, Any], errors).values())
    return " ".join(parts)


def parse_retry_after(value: str | None, *, now: datetime) -> float | None:
    """Parse a ``Retry-After`` header (delta-seconds or HTTP-date).

    Args:
        value: The header value, if any.
        now: Current time (aware UTC), for HTTP-date values.

    Returns:
        Seconds to wait (never negative), or ``None`` if absent or unparseable.
    """
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - now).total_seconds())


def map_status_error(
    *,
    status: int,
    reason: str,
    body: Any,
    headers: Mapping[str, str],
    method: str,
    path: str,
    target: str,
    now: datetime,
) -> HarnessError:
    """Classify a non-2xx Proxmox response.

    Args:
        status: HTTP status code.
        reason: HTTP reason phrase (PVE puts its error message here).
        body: Decoded JSON body, or ``None`` if it was not JSON.
        headers: Response headers (for ``Retry-After``).
        method: Request method, for the owner-safe message.
        path: API path without query, for the owner-safe message.
        target: Host the request went to.
        now: Current time (aware UTC).

    Returns:
        The SDK error to raise. Its message names the call and status only.
    """
    call = f"{method} {path}"
    text = _reason_text(reason, body)
    if status == 401:
        return AuthRejected(f"Proxmox rejected the API token (HTTP 401) on {call}", target=target)
    if status == 403:
        return PermissionDenied(
            f"the API token lacks a privilege for {call} (HTTP 403)", target=target
        )
    if status == 404 or (status == 500 and _MISSING.search(text)):
        return NotFound(f"Proxmox reports the object does not exist ({call})", target=target)
    if status == 409 or (status == 500 and _EXISTS.search(text)):
        return Conflict(f"Proxmox reports a conflicting object ({call})", target=target)
    if status == 500 and _LOCKED.search(text):
        return Conflict(f"the object is locked on Proxmox ({call})", target=target)
    if status == 429:
        return RateLimited(
            f"Proxmox asked the harness to slow down ({call})",
            target=target,
            retry_after_seconds=parse_retry_after(headers.get("retry-after"), now=now),
        )
    if status == 501:
        # pveproxy's answer for a path this PVE version does not implement.
        return NotFound(f"Proxmox does not implement {call} (HTTP 501)", target=target)
    if status == PVE_NODE_UNREACHABLE:
        return TargetUnavailable(
            f"the Proxmox proxy could not reach the node (HTTP 595) on {call}", target=target
        )
    if status >= 500:
        return TargetUnavailable(f"Proxmox failed with HTTP {status} on {call}", target=target)
    return InvalidInput(f"Proxmox rejected the request (HTTP {status}) on {call}", target=target)
