"""The :class:`~homelab_harness_sdk.ToolContext` core gives each tool call."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any

from homelab_harness.capabilities import AnyCapability
from homelab_harness.targets import TargetRegistry
from homelab_harness_sdk.errors import PermissionDenied


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CoreToolContext:
    """Hands a tool adapters bound to the credential tier it declared.

    Attributes:
        used_targets: Names of the targets the tool opened, for the audit record.
    """

    def __init__(
        self,
        *,
        capability: AnyCapability,
        registry: TargetRegistry,
        credential_tier: str,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Bind the context to one tool call.

        Args:
            capability: The tool's capability.
            registry: Registered targets.
            credential_tier: The tier the tool declared.
            clock: Source of aware UTC time.
        """
        self._capability = capability
        self._registry = registry
        self._tier = credential_tier
        self._clock = clock
        self.used_targets: list[str] = []

    @property
    def targets(self) -> Sequence[str]:
        """Names of this capability's targets."""
        return self._registry.names(self._capability.name)

    def adapter(self, target: str | None = None) -> AbstractAsyncContextManager[Any]:
        """Open an adapter for a target with this tool's credential tier.

        Raises:
            InvalidInput: If the target is unknown or ambiguous.
            PermissionDenied: If the target has no credential for the tier.
        """
        resolved = self._registry.get(self._capability.name, target)
        credential = resolved.credentials.get(self._tier)
        if credential is None:
            raise PermissionDenied(
                f"target {resolved.name!r} has no {self._tier!r} credential configured"
            )
        if resolved.name not in self.used_targets:
            self.used_targets.append(resolved.name)
        return self._capability.connect(resolved.config, credential)

    def now(self) -> datetime:
        """Current aware UTC time."""
        return self._clock()
