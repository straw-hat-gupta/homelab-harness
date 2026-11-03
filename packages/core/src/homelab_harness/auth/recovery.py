"""Owner recovery codes (pure logic).

A code looks like ``K7QM-2XRT-9WHC-PD4N``: the first group is a public lookup
key that finds the row, and the remaining three groups (about 59 random bits) are the
secret, stored only as a salted scrypt hash. One lookup means one scrypt per
attempt, and the login endpoint is rate-limited, so the secret cannot be guessed online.

Why scrypt and not argon2id: both are memory-hard. scrypt is in the standard
library (``hashlib.scrypt``, OpenSSL), so it adds no dependency for ten hashes
that are checked a handful of times in the harness's lifetime.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

# Crockford-style alphabet: no 0/O, 1/I/L or U, so a code copied from paper is unambiguous.
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
_GROUP = 4
_GROUPS = 4
CODE_COUNT = 10

# 16 MiB and ~50 ms per hash on a small host; RFC 7914 parameters.
_N, _R, _P = 2**14, 8, 1
_SALT_BYTES = 16
_DKLEN = 32
_SCHEME = "scrypt"


def _group() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_GROUP))


def generate_codes(count: int = CODE_COUNT) -> list[str]:
    """Return ``count`` new codes with distinct lookup groups."""
    codes: list[str] = []
    lookups: set[str] = set()
    while len(codes) < count:
        lookup = _group()
        if lookup in lookups:
            continue
        lookups.add(lookup)
        codes.append("-".join([lookup, *(_group() for _ in range(_GROUPS - 1))]))
    return codes


def split_code(code: str) -> tuple[str, str] | None:
    """Normalize what the owner typed and split it into (lookup, secret).

    Case, spaces and dashes do not matter. Returns ``None`` for anything that
    cannot be a code, so malformed input never reaches scrypt.
    """
    compact = "".join(code.split()).replace("-", "").upper()
    if len(compact) != _GROUP * _GROUPS or any(c not in _ALPHABET for c in compact):
        return None
    return compact[:_GROUP], compact[_GROUP:]


def hash_secret(secret: str) -> str:
    """Return the stored form ``scrypt$N$r$p$salt$hash`` (base64) of a code's secret part."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(secret.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return "$".join([_SCHEME, str(_N), str(_R), str(_P), _b64(salt), _b64(digest)])


def verify_secret(secret: str, stored: str) -> bool:
    """Check a code's secret part against its stored hash in constant time."""
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != _SCHEME:
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            secret.encode(),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()
