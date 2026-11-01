"""Validation of audit input (pure logic).

The audit log is the record of what happened, so it must stay small and free of
target content. These rules bound what a caller can put in it: a dotted ``kind``,
a known actor form, identifier-shaped references, and a ``data`` object of short
scalars (identifiers and counts), not payloads.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from homelab_harness_sdk.errors import InvalidInput

KIND_MAX = 64
ACTOR_MAX = 160
REF_MAX = 200
DATA_MAX_BYTES = 4096
DATA_MAX_DEPTH = 3
STRING_MAX = 256

_KIND = re.compile(rf"^(?=.{{1,{KIND_MAX}}}$)[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_CLIENT_ACTOR = re.compile(rf"^client:[A-Za-z0-9][A-Za-z0-9._:@-]{{0,{ACTOR_MAX - 8}}}$")
_REF = re.compile(rf"^[A-Za-z0-9][A-Za-z0-9._:/@-]{{0,{REF_MAX - 1}}}$")
_DATA_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FIXED_ACTORS = frozenset({"owner", "system"})

type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None


@dataclass(frozen=True, slots=True)
class AuditInput:
    """Validated fields for one audit event, ready to redact and insert."""

    kind: str
    actor: str
    plan_id: str | None
    job_id: str | None
    target: str | None
    data: dict[str, JsonValue]


def validate_audit_input(
    *,
    kind: str,
    actor: str,
    plan_id: str | None,
    job_id: str | None,
    target: str | None,
    data: Mapping[str, object] | None,
) -> AuditInput:
    """Check and normalize the fields of one audit event.

    Args:
        kind: Dotted event name, for example ``plan.created``.
        actor: ``owner``, ``system``, or ``client:<client_id>``.
        plan_id: Plan the event concerns, if any.
        job_id: Job the event concerns, if any.
        target: Target reference (for example ``pve1``), if any.
        data: Identifiers and counts. Values are JSON scalars (strings up to
            256 characters), or lists and objects of them, nested at most three
            levels deep and 4 KiB when serialized.

    Returns:
        The validated input, with ``data`` converted to plain JSON types.

    Raises:
        InvalidInput: If any field breaks the rules. Messages name the field,
            never its value.
    """
    if not _KIND.match(kind):
        raise InvalidInput("audit kind must be dotted lowercase, like 'plan.created'")
    if actor not in _FIXED_ACTORS and not _CLIENT_ACTOR.match(actor):
        raise InvalidInput("audit actor must be 'owner', 'system' or 'client:<id>'")
    for name, ref in (("plan_id", plan_id), ("job_id", job_id), ("target", target)):
        if ref is not None and not _REF.match(ref):
            raise InvalidInput(f"audit {name} is not a valid identifier")
    clean = _json_object(data or {}, depth=1)
    if len(json.dumps(clean, separators=(",", ":")).encode()) > DATA_MAX_BYTES:
        raise InvalidInput(f"audit data exceeds {DATA_MAX_BYTES} bytes")
    return AuditInput(
        kind=kind, actor=actor, plan_id=plan_id, job_id=job_id, target=target, data=clean
    )


def _json_object(value: Mapping[Any, object], *, depth: int) -> dict[str, JsonValue]:
    if depth > DATA_MAX_DEPTH:
        raise InvalidInput(f"audit data nests deeper than {DATA_MAX_DEPTH} levels")
    out: dict[str, JsonValue] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not _DATA_KEY.match(key):
            raise InvalidInput("audit data keys must be lowercase identifiers")
        out[key] = _json_value(item, depth=depth)
    return out


def _json_value(value: object, *, depth: int) -> JsonValue:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise InvalidInput("audit data numbers must be finite")
        return value
    if isinstance(value, str):
        if len(value) > STRING_MAX:
            raise InvalidInput(f"audit data strings are limited to {STRING_MAX} characters")
        return value
    if isinstance(value, Mapping):
        return _json_object(cast(Mapping[Any, object], value), depth=depth + 1)
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        if depth + 1 > DATA_MAX_DEPTH:
            raise InvalidInput(f"audit data nests deeper than {DATA_MAX_DEPTH} levels")
        return [_json_value(v, depth=depth + 1) for v in cast(Sequence[object], value)]
    raise InvalidInput("audit data values must be JSON scalars, lists or objects")
