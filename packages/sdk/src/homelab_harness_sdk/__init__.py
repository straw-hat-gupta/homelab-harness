"""Capability contract for homelab-harness.

Capabilities import only from this package, never from ``homelab_harness``
(the core), so they can be added without touching the control plane.
"""

from homelab_harness_sdk.errors import (
    AmbiguousOutcome,
    AuthRejected,
    Conflict,
    HarnessError,
    InvalidInput,
    NotFound,
    PermissionDenied,
    RateLimited,
    TargetUnavailable,
)
from homelab_harness_sdk.policy import RetryClass, Tier

__all__ = [
    "AmbiguousOutcome",
    "AuthRejected",
    "Conflict",
    "HarnessError",
    "InvalidInput",
    "NotFound",
    "PermissionDenied",
    "RateLimited",
    "RetryClass",
    "TargetUnavailable",
    "Tier",
]
