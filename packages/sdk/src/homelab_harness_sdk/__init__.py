"""Capability contract for homelab-harness.

Capabilities import only from this package, never from ``homelab_harness``
(the core), so they can be added without touching the control plane.
"""

from homelab_harness_sdk.capability import (
    ENTRY_POINT_GROUP,
    SECRET_HANDLE_PREFIX,
    SECRET_NAME_PATTERN,
    Capability,
    Credential,
    CredentialFile,
    Manifest,
    TargetConfig,
)
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
from homelab_harness_sdk.tools import (
    ReadTool,
    ToolContext,
    ToolInput,
    ToolOutput,
    Untrusted,
    read_tool,
)

__all__ = [
    "ENTRY_POINT_GROUP",
    "SECRET_HANDLE_PREFIX",
    "SECRET_NAME_PATTERN",
    "AmbiguousOutcome",
    "AuthRejected",
    "Capability",
    "Conflict",
    "Credential",
    "CredentialFile",
    "HarnessError",
    "InvalidInput",
    "Manifest",
    "NotFound",
    "PermissionDenied",
    "RateLimited",
    "ReadTool",
    "RetryClass",
    "TargetConfig",
    "TargetUnavailable",
    "Tier",
    "ToolContext",
    "ToolInput",
    "ToolOutput",
    "Untrusted",
    "read_tool",
]
