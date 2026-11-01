"""Risk tiers and retry classes shared by core policy and capabilities.

Definitions follow docs/spec/safety-model.md. Capabilities may suggest a tier;
only core policy assigns one.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class Tier(IntEnum):
    """Risk tier of an operation. Higher is riskier; comparisons are meaningful."""

    T0 = 0
    """Read: no side effect, no plan."""
    T1 = 1
    """Reversible and inside harness-owned scope; may be auto-approved."""
    T2 = 2
    """Recoverable change the owner cares about; needs owner approval."""
    T3 = 3
    """Destructive or lockout risk; approval plus typed confirmation."""


class RetryClass(StrEnum):
    """Whether an executor step may be repeated after a failure or crash."""

    READ = "read"
    """No side effect; always safe to repeat."""
    IDEMPOTENT = "idempotent"
    """Repeating converges to the same state (create-if-absent, PUT full config)."""
    UNSAFE = "unsafe"
    """Must run at most once; an unknown outcome ends the job as uncertain."""

    @property
    def may_retry(self) -> bool:
        """Whether a failed attempt of this class may be retried automatically."""
        return self is not RetryClass.UNSAFE
