"""Masking of secrets in anything the harness emits (S9, R-16).

Two layers:

* **Key-based:** values under keys that look sensitive (``token``, ``password``,
  ``authorization`` ...) are replaced, whatever they contain.
* **Value-based:** exact secret values registered at runtime (by the vault when it
  decrypts something) are masked wherever they appear in strings, including their
  base64, URL-encoded and hex forms, because those are how secrets usually leak.

This module is pure logic with no Django/FastAPI imports so every emitter (logs,
traces, previews, error responses) can share it.
"""

from __future__ import annotations

import base64
import re
import threading
import urllib.parse
from collections.abc import Mapping, Sequence
from typing import Any, cast

MASK = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"(pass(word|wd|phrase)?|secret|token|api[_-]?key|authori[sz]ation|cookie|"
    r"ticket|private[_-]?key|credential|session)",
    re.IGNORECASE,
)
# Values shorter than this are not registered: masking "a" or "true" everywhere would
# destroy logs without protecting anything real.
_MIN_SECRET_LENGTH = 6


def _variants(secret: str) -> set[str]:
    raw = secret.encode()
    forms = {
        secret,
        urllib.parse.quote(secret, safe=""),
        base64.b64encode(raw).decode(),
        base64.urlsafe_b64encode(raw).decode(),
        raw.hex(),
    }
    # Unpadded base64 is common in tokens and URLs.
    forms |= {f.rstrip("=") for f in forms}
    return {f for f in forms if len(f) >= _MIN_SECRET_LENGTH}


class Redactor:
    """Masks sensitive keys and registered secret values in nested data.

    Thread-safe; one process-wide instance is exposed as :data:`redactor`.
    """

    def __init__(self) -> None:
        """Create an empty redactor."""
        self._lock = threading.Lock()
        self._needles: frozenset[str] = frozenset()
        self._pattern: re.Pattern[str] | None = None

    def register(self, secret: str) -> None:
        """Mask this value (and its common encodings) from now on.

        Args:
            secret: A plaintext secret value. Short values are ignored.
        """
        if len(secret) < _MIN_SECRET_LENGTH:
            return
        with self._lock:
            needles = self._needles | _variants(secret)
            if needles == self._needles:
                return
            self._needles = frozenset(needles)
            # Longest first so a value is masked whole rather than partially.
            ordered = sorted(self._needles, key=len, reverse=True)
            self._pattern = re.compile("|".join(re.escape(n) for n in ordered))

    def clear(self) -> None:
        """Forget all registered values (used by tests)."""
        with self._lock:
            self._needles = frozenset()
            self._pattern = None

    def scrub_text(self, text: str) -> str:
        """Return ``text`` with every registered secret form masked.

        Args:
            text: Any string about to leave the process.

        Returns:
            The masked string.
        """
        pattern = self._pattern
        if pattern is None:
            return text
        return pattern.sub(MASK, text)

    def scrub(self, value: Any, *, key: str | None = None) -> Any:
        """Recursively mask a value about to be logged, traced or returned.

        Args:
            value: Arbitrary nested data (mappings, sequences, scalars).
            key: The mapping key this value sits under, if any.

        Returns:
            A masked copy; the input is not modified.
        """
        if key is not None and _SENSITIVE_KEY.search(key) and value not in (None, ""):
            return MASK
        if isinstance(value, str):
            return self.scrub_text(value)
        if isinstance(value, bytes):
            return self.scrub_text(value.decode("utf-8", errors="replace"))
        if isinstance(value, Mapping):
            mapping = cast(Mapping[object, Any], value)
            return {k: self.scrub(v, key=str(k)) for k, v in mapping.items()}
        if isinstance(value, Sequence):
            items = cast(Sequence[Any], value)
            return [self.scrub(v) for v in items]
        return value

    def scrub_values(self, value: Any) -> Any:
        """Mask registered secret values in nested data, leaving keys out of it.

        For structured results whose shape is a published schema: key-based
        masking would turn an integer under a key like ``token_count`` into a
        string and break the schema, while the shape itself is already reviewed.

        Args:
            value: JSON-like nested data.

        Returns:
            A copy with every registered secret form masked inside strings.
        """
        if isinstance(value, str):
            return self.scrub_text(value)
        if isinstance(value, Mapping):
            mapping = cast(Mapping[object, Any], value)
            return {k: self.scrub_values(v) for k, v in mapping.items()}
        if isinstance(value, list | tuple):
            items = cast(Sequence[Any], value)
            return [self.scrub_values(v) for v in items]
        return value


redactor = Redactor()
"""Process-wide redactor shared by logging, telemetry and error handling."""
