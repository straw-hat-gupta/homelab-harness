"""Shared error types that every capability adapter maps provider failures to.

Adapters translate HTTP statuses, SSH failures and SDK exceptions into these
classes so that core policy (retries, credential health, job outcomes) can be
written once. Messages must be safe to show the owner: no provider response
bodies, URLs with credentials, or secret values.
"""

from __future__ import annotations


class HarnessError(Exception):
    """Base class for errors raised across the capability boundary.

    Attributes:
        retryable: Whether repeating the same call may succeed. Only consulted
            for steps whose retry class permits retries.
        safe_message: Text that may be shown to the owner or returned to a
            client. Never contains provider bodies or secrets.
    """

    retryable: bool = False

    def __init__(self, safe_message: str, *, target: str | None = None) -> None:
        """Create the error.

        Args:
            safe_message: Owner-safe description of what failed.
            target: Optional target name (for example a node) for context.
        """
        super().__init__(safe_message)
        self.safe_message = safe_message
        self.target = target


class InvalidInput(HarnessError):
    """The request was malformed or failed validation; do not retry."""


class AuthRejected(HarnessError):
    """The target definitively rejected the credential (for example a revoked token).

    This is the only error that may mark a credential unusable (R-14).
    """


class PermissionDenied(HarnessError):
    """The credential is valid but lacks the privilege for this operation."""


class NotFound(HarnessError):
    """The referenced resource does not exist on the target."""


class Conflict(HarnessError):
    """The target refused because of concurrent state (a lock, a digest mismatch)."""


class RateLimited(HarnessError):
    """The target asked us to slow down."""

    retryable = True

    def __init__(
        self,
        safe_message: str,
        *,
        target: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        """Create the error.

        Args:
            safe_message: Owner-safe description.
            target: Optional target name.
            retry_after_seconds: Delay requested by the target, if it sent one.
        """
        super().__init__(safe_message, target=target)
        self.retry_after_seconds = retry_after_seconds


class TargetUnavailable(HarnessError):
    """The target could not be reached, or failed before acting (connect error, 503).

    Transient by nature: never a reason to disable a credential.
    """

    retryable = True


class AmbiguousOutcome(HarnessError):
    """The request may have taken effect but we cannot tell (read timeout after send).

    Jobs that hit this end as ``uncertain`` and are never replayed (S6, R-02).
    """
