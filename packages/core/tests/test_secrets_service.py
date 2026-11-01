"""The vault service against real Postgres: CRUD, rotation, revocation, crypto-shred, rewrap."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from homelab_harness.audit.service import AuditWriter
from homelab_harness.db.engine import create_engine, create_session_factory
from homelab_harness.redaction import MASK, Redactor
from homelab_harness.secrets.crypto import SecretIntegrityError
from homelab_harness.secrets.keys import (
    EnvKeyProvider,
    KeyProviderError,
    generate_kek,
    keyring_line,
)
from homelab_harness.secrets.kinds import SecretKind
from homelab_harness.secrets.payloads import parse_fields
from homelab_harness.secrets.service import VaultService
from homelab_harness.settings import Environment, Settings
from homelab_harness_sdk.errors import Conflict, InvalidInput, NotFound

KINDS = list(SecretKind)


def keyring(*keks):
    return EnvKeyProvider(",".join(keyring_line(k) for k in keks), env=Environment.TEST)


def vault_for(sessions, provider):
    # An empty redactor in the audit writer: a leak must show up, not be masked away.
    return VaultService(sessions, keys=provider, audit=AuditWriter(sessions, scrubber=Redactor()))


@pytest.fixture
def kek():
    return generate_kek("kek-1")


@pytest.fixture
def vault(sessions, kek):
    return vault_for(sessions, keyring(kek))


@pytest.fixture
def name():
    return f"t-{uuid.uuid4().hex[:10]}"


async def audit_text(sessions, vault_id):
    async with sessions() as session:
        rows = await session.execute(
            text("SELECT kind, actor, data::text FROM audit_events WHERE data->>'vault_id' = :v"),
            {"v": vault_id},
        )
    return [tuple(r) for r in rows]


def fields_of(kind, sample):
    value, fields, _, _ = sample
    return parse_fields(kind, value=value, fields=fields)


@pytest.mark.parametrize("kind", KINDS)
async def test_round_trip_per_kind(vault, sessions, name, kind, kind_sample):
    sample = kind_sample(kind.value)
    _, _, metadata, canary = sample
    fields = fields_of(kind, sample)
    expires = datetime(2027, 1, 1, tzinfo=UTC)
    created = await vault.create(
        name=name,
        fields=fields,
        metadata=metadata,
        actor="owner",
        description="for tests",
        tags=["lab", "test", "lab"],
        expires_at=expires,
        rotate_every=timedelta(days=90),
    )
    assert created.kind is kind
    assert created.current_version == 1
    assert created.tags == ("lab", "test")
    assert canary not in repr(created)

    shown = await vault.get_metadata(name=name)
    assert shown.expires_at == expires
    assert shown.rotate_every == timedelta(days=90)
    assert [v.version for v in shown.versions] == [1]
    assert shown.versions[0].kek_id == "kek-1"
    assert canary not in repr(shown) + str(shown.metadata)
    assert name in [s.name for s in await vault.list_secrets()]

    resolved = await vault.resolve(name=name, consumer="test:round-trip", purpose="test")
    assert resolved.version == 1
    assert resolved.fields == fields

    events = await audit_text(sessions, str(created.id))
    assert [e[0] for e in events] == ["secret.created", "secret.used"]
    for _, _, data in events:
        assert canary not in data
        assert MASK not in data  # no audit key looks like a secret, so nothing was masked
    used = events[1][2]
    assert '"consumer": "test:round-trip"' in used
    assert '"purpose": "test"' in used


async def test_stored_rows_hold_no_plaintext(vault, sessions, name, kind_sample, engine):
    sample = kind_sample("password")
    info = await vault.create(
        name=name, fields=fields_of(SecretKind.PASSWORD, sample), metadata={}, actor="owner"
    )
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT s.metadata::text, v.ciphertext, v.wrapped_dek FROM secrets s "
                    "JOIN secret_versions v ON v.secret_id = s.id WHERE s.id = :i"
                ),
                {"i": info.id},
            )
        ).one()
    canary = sample[3].encode()
    assert canary not in row[0].encode()
    assert canary not in bytes(row[1])
    assert canary not in bytes(row[2])


async def test_rotate_creates_a_new_version_and_resolve_returns_it(
    vault, sessions, name, kind_sample
):
    first = kind_sample("proxmox_token")
    second = kind_sample("proxmox_token")
    info = await vault.create(
        name=name,
        fields=fields_of(SecretKind.PROXMOX_TOKEN, first),
        metadata=first[2],
        actor="owner",
    )
    rotated = await vault.add_version(
        name=name, fields=fields_of(SecretKind.PROXMOX_TOKEN, second), actor="owner"
    )
    assert rotated.current_version == 2
    assert rotated.rotated_at is not None
    assert [v.version for v in rotated.versions] == [1, 2]
    assert rotated.metadata["token_id"] == "harness@pve!read"  # carried over
    resolved = await vault.resolve(name=name, consumer="test", purpose="test")
    assert resolved.version == 2
    assert resolved.fields.secret.reveal() == second[0]
    kinds = [e[0] for e in await audit_text(sessions, str(info.id))]
    assert kinds == ["secret.created", "secret.rotated", "secret.used"]


async def test_rotating_an_ssh_key_rederives_the_public_key(vault, name, kind_sample):
    first, second = kind_sample("ssh_key"), kind_sample("ssh_key")
    created = await vault.create(
        name=name, fields=fields_of(SecretKind.SSH_KEY, first), metadata=first[2], actor="owner"
    )
    rotated = await vault.add_version(
        name=name, fields=fields_of(SecretKind.SSH_KEY, second), actor="owner"
    )
    assert rotated.metadata["public_key"] != created.metadata["public_key"]
    assert rotated.metadata["comment"] == "test@harness"


async def test_rotate_refuses_another_kind(vault, name, kind_sample):
    pw = kind_sample("password")
    await vault.create(
        name=name, fields=fields_of(SecretKind.PASSWORD, pw), metadata={}, actor="owner"
    )
    with pytest.raises(InvalidInput, match="is a password"):
        await vault.add_version(
            name=name, fields=fields_of(SecretKind.API_TOKEN, kind_sample("api_token")), actor="o"
        )
    with pytest.raises(NotFound):
        await vault.add_version(
            name="never-stored", fields=fields_of(SecretKind.PASSWORD, pw), actor="owner"
        )


async def test_names_are_unique_and_validated(vault, name, kind_sample):
    pw = fields_of(SecretKind.PASSWORD, kind_sample("password"))
    await vault.create(name=name, fields=pw, metadata={}, actor="owner")
    with pytest.raises(Conflict, match="already exists"):
        await vault.create(name=name, fields=pw, metadata={}, actor="owner")
    for bad in ("Has Caps", "", "-dash", "a/b", "x" * 129):
        with pytest.raises(InvalidInput):
            await vault.create(name=bad, fields=pw, metadata={}, actor="owner")
    with pytest.raises(InvalidInput, match="tags"):
        await vault.create(name=f"{name}-t", fields=pw, metadata={}, actor="owner", tags=["A B"])
    with pytest.raises(InvalidInput, match="positive"):
        await vault.create(
            name=f"{name}-r", fields=pw, metadata={}, actor="owner", rotate_every=timedelta(0)
        )


async def test_revoke_blocks_resolve_until_rotated(vault, sessions, name, kind_sample):
    sample = kind_sample("api_token")
    info = await vault.create(
        name=name, fields=fields_of(SecretKind.API_TOKEN, sample), metadata={}, actor="owner"
    )
    revoked = await vault.revoke(name=name, actor="owner")
    assert revoked.revoked_at is not None
    await vault.revoke(name=name, actor="owner")  # idempotent, one event
    with pytest.raises(Conflict, match="revoked"):
        await vault.resolve(name=name, consumer="test", purpose="test")
    await vault.add_version(
        name=name, fields=fields_of(SecretKind.API_TOKEN, kind_sample("api_token")), actor="owner"
    )
    assert (await vault.resolve(name=name, consumer="test", purpose="test")).version == 2
    kinds = [e[0] for e in await audit_text(sessions, str(info.id))]
    assert kinds.count("secret.revoked") == 1


async def test_resolve_refuses_bad_labels_and_unknown_names(vault):
    with pytest.raises(InvalidInput, match="consumer"):
        await vault.resolve(name="x", consumer="has space", purpose="test")
    with pytest.raises(NotFound):
        await vault.resolve(name="never-stored", consumer="test", purpose="test")


async def test_delete_crypto_shreds_every_version(vault, sessions, name, kind_sample, engine):
    sample = kind_sample("password")
    info = await vault.create(
        name=name, fields=fields_of(SecretKind.PASSWORD, sample), metadata={}, actor="owner"
    )
    await vault.add_version(
        name=name, fields=fields_of(SecretKind.PASSWORD, kind_sample("password")), actor="owner"
    )
    with pytest.raises(InvalidInput, match="confirmation"):
        await vault.delete(name=name, confirm_name="wrong", actor="owner")
    assert await vault.delete(name=name, confirm_name=name, actor="owner") == 2
    async with engine.connect() as conn:
        left = await conn.scalar(
            text("SELECT count(*) FROM secret_versions WHERE secret_id = :i"), {"i": info.id}
        )
        meta = await conn.scalar(text("SELECT count(*) FROM secrets WHERE id = :i"), {"i": info.id})
    assert left == 0
    assert meta == 0
    with pytest.raises(NotFound):
        await vault.resolve(name=name, consumer="test", purpose="test")
    with pytest.raises(NotFound):
        await vault.delete(name=name, confirm_name=name, actor="owner")
    events = await audit_text(sessions, str(info.id))
    assert events[-1][0] == "secret.deleted"
    assert '"versions_destroyed": 2' in events[-1][2]
    # The name can be used again: nothing of the old secret is left to collide with.
    await vault.create(
        name=name, fields=fields_of(SecretKind.PASSWORD, sample), metadata={}, actor="owner"
    )


async def test_a_record_moved_to_another_secret_fails_to_open(vault, name, kind_sample, engine):
    a = await vault.create(
        name=name,
        fields=fields_of(SecretKind.PASSWORD, kind_sample("password")),
        metadata={},
        actor="owner",
    )
    b = await vault.create(
        name=f"{name}-b",
        fields=fields_of(SecretKind.PASSWORD, kind_sample("password")),
        metadata={},
        actor="owner",
    )
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE secret_versions SET ciphertext = src.ciphertext, nonce = src.nonce, "
                "wrapped_dek = src.wrapped_dek, dek_nonce = src.dek_nonce "
                "FROM secret_versions src WHERE src.secret_id = :a "
                "AND secret_versions.secret_id = :b"
            ),
            {"a": a.id, "b": b.id},
        )
    with pytest.raises(SecretIntegrityError):
        await vault.resolve(name=f"{name}-b", consumer="test", purpose="test")


@pytest.fixture
async def fresh_sessions(fresh_migrated_url):
    engine = create_engine(
        Settings(env=Environment.TEST, database_url=SecretStr(fresh_migrated_url))
    )
    yield create_session_factory(engine)
    await engine.dispose()


async def ciphertexts(sessions):
    async with sessions() as session:
        rows = await session.execute(
            text("SELECT id, ciphertext, kek_id FROM secret_versions ORDER BY id")
        )
    return [(r[0], bytes(r[1]), r[2]) for r in rows]


async def test_rewrap_all_moves_every_dek_to_the_new_kek_and_is_idempotent(
    fresh_sessions, kind_sample
):
    old, new = generate_kek("kek-old"), generate_kek("kek-new")
    before_rotation = vault_for(fresh_sessions, keyring(old))
    stored = {}
    for kind in KINDS:
        sample = kind_sample(kind.value)
        fields = fields_of(kind, sample)
        await before_rotation.create(
            name=f"s-{kind.value}", fields=fields, metadata=sample[2], actor="owner"
        )
        stored[kind] = fields
    await before_rotation.add_version(
        name="s-password", fields=stored[SecretKind.PASSWORD], actor="owner"
    )
    before = await ciphertexts(fresh_sessions)
    assert {k for _, _, k in before} == {"kek-old"}

    # The new KEK goes first in the keyring; the old one stays until the rewrap is done.
    during = vault_for(fresh_sessions, keyring(new, old))
    assert await during.versions_on_other_keks() == len(KINDS) + 1
    report = await during.rewrap_all(actor="owner")
    assert (report.kek_id, report.rewrapped, report.already_current, report.failed) == (
        "kek-new",
        len(KINDS) + 1,
        0,
        0,
    )
    after = await ciphertexts(fresh_sessions)
    assert [(i, c) for i, c, _ in after] == [(i, c) for i, c, _ in before]  # values untouched
    assert {k for _, _, k in after} == {"kek-new"}
    assert await during.versions_on_other_keks() == 0

    again = await during.rewrap_all(actor="owner")
    assert (again.rewrapped, again.already_current, again.failed) == (0, len(KINDS) + 1, 0)

    # With the old KEK gone, every secret still opens.
    only_new = vault_for(fresh_sessions, keyring(new))
    for kind, fields in stored.items():
        resolved = await only_new.resolve(name=f"s-{kind.value}", consumer="test", purpose="test")
        assert resolved.fields == fields
    with pytest.raises(KeyProviderError):
        await vault_for(fresh_sessions, keyring(old)).resolve(
            name="s-kv", consumer="test", purpose="test"
        )


async def test_rewrap_resumes_a_mixed_vault_and_reports_versions_it_cannot_open(
    fresh_sessions, kind_sample
):
    k1, k2, lost = generate_kek("k1"), generate_kek("k2"), generate_kek("lost")
    for i, key in enumerate((k1, k2, k1, lost)):
        sample = kind_sample("password")
        await vault_for(fresh_sessions, keyring(key)).create(
            name=f"p-{i}",
            fields=fields_of(SecretKind.PASSWORD, sample),
            metadata={},
            actor="owner",
        )
    # As after an interrupted run: one version is already on k2. "lost" is not loaded.
    report = await vault_for(fresh_sessions, keyring(k2, k1)).rewrap_all(actor="owner")
    assert (report.rewrapped, report.already_current, report.failed) == (2, 1, 1)
    remaining = {k for _, _, k in await ciphertexts(fresh_sessions)}
    assert remaining == {"k2", "lost"}
    async with fresh_sessions() as session:
        (event,) = (
            await session.execute(
                text("SELECT data FROM audit_events WHERE kind = 'vault.kek_rotated'")
            )
        ).one()
    assert event == {"kek_id": "k2", "rewrapped": 2, "already_current": 1, "failed": 1}
