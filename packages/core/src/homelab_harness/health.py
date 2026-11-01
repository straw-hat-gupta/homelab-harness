"""Readiness checks.

Subsystems (database, DBOS, vault, target syncs) register a check here as they
land. ``/readyz`` runs them all with a timeout. A check failing means the harness
cannot serve (database down); a check reporting *degraded* means it can serve with
reduced function (one target unreachable), which must not take the process out of
rotation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum


class CheckStatus(StrEnum):
    """Outcome of one readiness check, ordered from best to worst."""

    OK = "ok"
    DEGRADED = "degraded"
    FAIL = "fail"


_SEVERITY = {CheckStatus.OK: 0, CheckStatus.DEGRADED: 1, CheckStatus.FAIL: 2}


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Result of one check. ``detail`` must be owner-safe (no secrets, no bodies)."""

    status: CheckStatus
    detail: str = ""


CheckFn = Callable[[], Awaitable[CheckResult]]


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """Aggregate of all checks."""

    status: CheckStatus
    checks: dict[str, CheckResult]


class ReadinessRegistry:
    """Named async checks run together by ``/readyz``."""

    def __init__(self, *, timeout_seconds: float = 2.0) -> None:
        """Create an empty registry.

        Args:
            timeout_seconds: Per-check time limit; a slow check counts as failed.
        """
        self._checks: dict[str, CheckFn] = {}
        self._timeout = timeout_seconds

    def register(self, name: str, check: CheckFn) -> None:
        """Add a check.

        Args:
            name: Unique, stable name shown in the report (for example ``database``).
            check: Coroutine function returning a :class:`CheckResult`.

        Raises:
            ValueError: If a check with this name is already registered.
        """
        if name in self._checks:
            raise ValueError(f"readiness check {name!r} already registered")
        self._checks[name] = check

    async def _run_one(self, check: CheckFn) -> CheckResult:
        try:
            return await asyncio.wait_for(check(), timeout=self._timeout)
        except TimeoutError:
            return CheckResult(CheckStatus.FAIL, "timed out")
        except Exception as exc:  # a broken check must not break the endpoint
            return CheckResult(CheckStatus.FAIL, f"check raised {type(exc).__name__}")

    async def run(self) -> ReadinessReport:
        """Run every check concurrently and aggregate to the worst status.

        Returns:
            The aggregate report; ``ok`` when no checks are registered.
        """
        names = list(self._checks)
        results = await asyncio.gather(*(self._run_one(self._checks[n]) for n in names))
        checks = dict(zip(names, results, strict=True))
        worst = max((r.status for r in results), key=_SEVERITY.__getitem__, default=CheckStatus.OK)
        return ReadinessReport(status=worst, checks=checks)
