"""Readiness checks per registered target: ``<capability>:<name>``.

A target that cannot be reached reports *degraded*, never *fail*: one lab
machine being down must not take the harness out of rotation.
"""

from __future__ import annotations

import asyncio

import structlog

from homelab_harness.capabilities import AnyCapability
from homelab_harness.health import CheckFn, CheckResult, CheckStatus
from homelab_harness.targets import Target
from homelab_harness_sdk import HarnessError

log = structlog.get_logger(__name__)

# Below the readiness registry's 2 s, so a slow target reports its own reason.
_TIMEOUT_SECONDS = 1.5


def target_check(capability: AnyCapability, target: Target) -> CheckFn:
    """Build a check that runs the capability's probe against one target.

    Args:
        capability: The target's capability.
        target: The target.

    Returns:
        A check reporting ``ok`` or ``degraded``. The detail is the error class
        name or a fixed word, never target text.
    """

    async def check() -> CheckResult:
        credential = target.credentials.get(capability.probe_credential)
        if credential is None:
            return CheckResult(CheckStatus.DEGRADED, f"no {capability.probe_credential} credential")
        try:
            async with asyncio.timeout(_TIMEOUT_SECONDS):
                async with capability.connect(target.config, credential) as adapter:
                    await capability.probe(adapter)
        except TimeoutError:
            return CheckResult(CheckStatus.DEGRADED, "timed out")
        except HarnessError as exc:
            log.warning("target_check_failed", target=target.name, error_type=type(exc).__name__)
            return CheckResult(CheckStatus.DEGRADED, type(exc).__name__)
        except Exception as exc:  # any probe failure means "degraded", never a crash
            log.warning("target_check_failed", target=target.name, error_type=type(exc).__name__)
            return CheckResult(CheckStatus.DEGRADED, "unreachable")
        return CheckResult(CheckStatus.OK)

    return check
