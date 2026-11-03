"""Fixed-window rate limits for the public auth endpoints (pure logic).

Why in memory and not in Postgres: the harness runs as one process for one
owner, so a per-process counter sees every request. A database counter would
add a write to every login and token call to defend against an attacker who
could only gain from a restart, and a restart already costs them their window.
If the harness ever runs more than one worker, each enforces its own limit,
which multiplies the budget by the worker count; that is documented.

Keys are ``(bucket, client address)`` plus a ``(bucket, "*")`` total per
bucket, so one address cannot exhaust the budget and many addresses together
cannot exceed it either.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Limit:
    """``per_client`` and ``total`` requests per ``window_seconds``."""

    per_client: int
    total: int
    window_seconds: float


@dataclass(frozen=True, slots=True)
class Decision:
    """Whether a request may proceed, and if not, when to retry."""

    allowed: bool
    retry_after_seconds: int = 0


_MAX_KEYS = 10_000


class RateLimiter:
    """Counts requests per bucket and client in fixed windows. Thread-safe."""

    def __init__(
        self, limits: dict[str, Limit], *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        """Create a limiter.

        Args:
            limits: Limit per bucket name.
            clock: Monotonic seconds; injectable for tests.
        """
        self._limits = limits
        self._clock = clock
        self._lock = threading.Lock()
        self._windows: dict[tuple[str, str], tuple[float, int]] = {}

    def check(self, bucket: str, client: str) -> Decision:
        """Count one request and decide whether it may proceed.

        Args:
            bucket: Endpoint group, a key of ``limits``.
            client: The caller's address.

        Returns:
            The decision. A refused request still counts, so hammering does not
            shorten the wait.

        Raises:
            KeyError: For an unknown bucket (a wiring bug).
        """
        limit = self._limits[bucket]
        now = self._clock()
        with self._lock:
            if len(self._windows) > _MAX_KEYS:
                self._evict(now)
            waits = [
                self._count((bucket, client), limit.per_client, limit.window_seconds, now),
                self._count((bucket, "*"), limit.total, limit.window_seconds, now),
            ]
        wait = max(waits)
        if wait > 0:
            return Decision(allowed=False, retry_after_seconds=max(1, math.ceil(wait)))
        return Decision(allowed=True)

    def _count(self, key: tuple[str, str], maximum: int, window: float, now: float) -> float:
        start, count = self._windows.get(key, (now, 0))
        if now - start >= window:
            start, count = now, 0
        count += 1
        self._windows[key] = (start, count)
        return 0.0 if count <= maximum else window - (now - start)

    def _evict(self, now: float) -> None:
        # Drop finished windows; bounded memory even under an address-spraying flood.
        longest = max(limit.window_seconds for limit in self._limits.values())
        self._windows = {k: v for k, v in self._windows.items() if now - v[0] < longest}


DEFAULT_LIMITS = {
    # Passkey and recovery-code login, and enrollment: a human does these rarely.
    "login": Limit(per_client=10, total=30, window_seconds=60),
    # Authorization requests (each may trigger one metadata document fetch).
    "authorize": Limit(per_client=30, total=60, window_seconds=60),
    # Token endpoint: clients refresh every few minutes; leave room for several.
    "token": Limit(per_client=30, total=120, window_seconds=60),
    # Dynamic client registration: legitimate clients register once.
    "register": Limit(per_client=5, total=20, window_seconds=3600),
}
"""Limits for the public auth endpoints."""
