import dataclasses
import os

import pytest

from homelab_harness.secrets.crypto import (
    EncryptedSecret,
    Kek,
    SecretIntegrityError,
    rewrap,
    seal,
    unseal,
)
from homelab_harness.secrets.keys import generate_kek

CANARY_VALUE = b"hh-canary-crypto-" + os.urandom(8).hex().encode()


@pytest.fixture
def kek():
    return generate_kek("kek-a")


@pytest.fixture
def sealed(kek):
    return seal(CANARY_VALUE, secret_id="sec-1", version=3, kind="api_token", kek=kek)


def _flip(data: bytes, index: int = 0) -> bytes:
    return data[:index] + bytes([data[index] ^ 0x01]) + data[index + 1 :]


def test_round_trip(sealed, kek):
    assert unseal(sealed, kek=kek) == CANARY_VALUE
    assert sealed.kek_id == "kek-a"
    assert CANARY_VALUE not in sealed.ciphertext


def test_repr_hides_ciphertext_and_wrapped_dek(sealed):
    text = repr(sealed)
    assert "ciphertext" not in text
    assert "wrapped_dek" not in text


@pytest.mark.parametrize(
    "change",
    [
        {"ciphertext": "flip"},
        {"nonce": "flip"},
        {"wrapped_dek": "flip"},
        {"dek_nonce": "flip"},
        {"secret_id": "sec-2"},
        {"version": 4},
        {"kind": "password"},
        {"ciphertext": "truncate"},
        {"nonce": "truncate"},
        {"wrapped_dek": "truncate"},
    ],
    ids=lambda c: "-".join(f"{k}:{v}" for k, v in c.items()),
)
def test_any_tampering_raises_integrity_error(sealed, kek, change):
    updates = {}
    for name, how in change.items():
        current = getattr(sealed, name)
        if how == "flip":
            updates[name] = _flip(current, len(current) // 2)
        elif how == "truncate":
            updates[name] = current[:-1]
        else:
            updates[name] = how
    tampered = dataclasses.replace(sealed, **updates)
    with pytest.raises(SecretIntegrityError):
        unseal(tampered, kek=kek)


def test_tampered_kek_id_raises_even_with_the_same_key(sealed, kek):
    # A record relabelled to another KEK id must not open, even if a key ring
    # happened to give the same bytes under the new id.
    relabelled = dataclasses.replace(sealed, kek_id="kek-b")
    with pytest.raises(SecretIntegrityError):
        unseal(relabelled, kek=Kek(kek_id="kek-b", key=kek.key))
    with pytest.raises(SecretIntegrityError):
        unseal(relabelled, kek=kek)


def test_wrong_kek_raises(sealed):
    with pytest.raises(SecretIntegrityError):
        unseal(sealed, kek=generate_kek("kek-a"))


def test_wrapped_dek_cannot_be_moved_to_another_record(kek):
    a = seal(b"value-a-123456", secret_id="sec-a", version=1, kind="password", kek=kek)
    b = seal(b"value-b-123456", secret_id="sec-b", version=1, kind="password", kek=kek)
    swapped = dataclasses.replace(b, wrapped_dek=a.wrapped_dek, dek_nonce=a.dek_nonce)
    with pytest.raises(SecretIntegrityError):
        unseal(swapped, kek=kek)


def test_rewrap_opens_with_new_kek_only_and_keeps_ciphertext(sealed, kek):
    new = generate_kek("kek-b")
    rotated = rewrap(sealed, old_kek=kek, new_kek=new)
    assert rotated.kek_id == "kek-b"
    assert rotated.ciphertext == sealed.ciphertext
    assert rotated.nonce == sealed.nonce
    assert rotated.wrapped_dek != sealed.wrapped_dek
    assert unseal(rotated, kek=new) == CANARY_VALUE
    with pytest.raises(SecretIntegrityError):
        unseal(rotated, kek=kek)
    with pytest.raises(SecretIntegrityError):
        unseal(rotated, kek=Kek(kek_id="kek-b", key=kek.key))


def test_rewrap_with_wrong_old_kek_raises(sealed):
    with pytest.raises(SecretIntegrityError):
        rewrap(sealed, old_kek=generate_kek("kek-a"), new_kek=generate_kek("kek-b"))


def test_nonces_and_deks_are_unique_across_many_seals(kek):
    records: list[EncryptedSecret] = [
        seal(b"same plaintext", secret_id="sec-1", version=1, kind="kv", kek=kek)
        for _ in range(2000)
    ]
    nonces = [r.nonce for r in records] + [r.dek_nonce for r in records]
    assert len(set(nonces)) == len(nonces)
    assert len({r.ciphertext for r in records}) == len(records)
    assert all(len(r.nonce) == 12 and len(r.dek_nonce) == 12 for r in records)


@pytest.mark.parametrize(
    "identity",
    [
        {"secret_id": "a|b", "version": 1, "kind": "kv"},
        {"secret_id": "", "version": 1, "kind": "kv"},
        {"secret_id": "s", "version": 0, "kind": "kv"},
        {"secret_id": "s", "version": 1, "kind": "Kv|x"},
    ],
)
def test_ambiguous_or_invalid_identity_is_rejected(kek, identity):
    with pytest.raises(ValueError, match="must"):
        seal(b"x", kek=kek, **identity)


@pytest.mark.parametrize("length", [0, 16, 31, 33])
def test_kek_must_be_256_bits(length):
    with pytest.raises(ValueError, match="32 bytes"):
        Kek(kek_id="k1", key=b"\x00" * length)


def test_kek_repr_hides_key():
    kek = generate_kek("k1")
    assert kek.key.hex() not in repr(kek)
    assert "key=" not in repr(kek)
