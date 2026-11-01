"""The ``database`` readiness check."""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from homelab_harness.health import CheckFn, CheckResult, CheckStatus

log = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 1.5  # below the registry's 2 s, so this check reports its own reason


def database_check(engine: AsyncEngine) -> CheckFn:
    """Build a check that runs ``SELECT 1`` with a time limit.

    Args:
        engine: The app engine.

    Returns:
        A readiness check reporting ``ok`` or ``fail``. The detail is a fixed,
        owner-safe word: driver errors can quote hosts, users or the URL.
    """

    async def check() -> CheckResult:
        try:
            async with asyncio.timeout(_TIMEOUT_SECONDS), engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except TimeoutError:
            return CheckResult(CheckStatus.FAIL, "timed out")
        except Exception as exc:  # any driver failure means "not ready"
            log.warning("database_check_failed", error_type=type(exc).__name__)
            return CheckResult(CheckStatus.FAIL, "unreachable")
        return CheckResult(CheckStatus.OK)

    return check
