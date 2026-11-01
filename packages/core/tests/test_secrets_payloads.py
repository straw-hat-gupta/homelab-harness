"""Intake parsing, derived metadata and key generation (pure logic)."""

import uuid

import pytest
from cryptography.hazmat.primitives import serialization

from homelab_harness.secrets.kinds import (
    KIND_MODELS,
    SecretKind,
    SshKeyFields,
    decode_fields,
    encode_fields,
)
from homelab_harness.secrets.payloads import (
    authorized_keys_line,
    carried_metadata,
    derive_metadata,
    generate_ssh_key,
    parse_fields,
    primary_value,
)
from homelab_harness_sdk.errors import InvalidInput

KINDS = list(SecretKind)


@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_parses_and_derives_metadata(kind, kind_sample):
    value, fields, metadata, canary = kind_sample(kind.value)
    parsed = parse_fields(kind, value=value, fields=fields)
    assert isinstance(parsed, KIND_MODELS[kind][0])
    assert decode_fields(kind, encode_fields(parsed)) == parsed
    assert canary not in repr(parsed)
    meta = derive_metadata(kind, parsed, metadata)
    assert isinstance(meta, KIND_MODELS[kind][1])
    assert canary not in meta.model_dump_json()


def test_value_and_fields_are_exclusive(kind_sample):
    value, _, _, _ = kind_sample("password")
    with pytest.raises(InvalidInput, match="exactly one"):
        parse_fields(SecretKind.PASSWORD, value=value, fields={"password": value})
    with pytest.raises(InvalidInput, match="exactly one"):
        parse_fields(SecretKind.PASSWORD, value=None, fields=None)
    with pytest.raises(InvalidInput, match="takes 'fields'"):
        parse_fields(SecretKind.KV, value=value, fields=None)


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        (SecretKind.PROXMOX_TOKEN, {"secret": "CANARY_NOT_A_UUID"}),
        (SecretKind.PASSWORD, {"password": "CANARY_X", "extra": "CANARY_Y"}),
        (SecretKind.KV, {"values": {"bad key": "CANARY_V"}}),
        (SecretKind.SSH_KEY, {"private_key": "CANARY_NOT_A_KEY"}),
        (SecretKind.FILE, {"content": "CANARY not base64!"}),
    ],
)
def test_invalid_fields_name_the_field_never_the_value(kind, fields):
    with pytest.raises(InvalidInput) as raised:
        parse_fields(kind, value=None, fields=fields)
    assert "CANARY" not in raised.value.safe_message
    assert str(kind) in raised.value.safe_message


def test_metadata_rules(kind_sample):
    value, _, _, _ = kind_sample("proxmox_token")
    token = parse_fields(SecretKind.PROXMOX_TOKEN, value=value, fields=None)
    with pytest.raises(InvalidInput, match="token_id"):
        derive_metadata(SecretKind.PROXMOX_TOKEN, token, {"token_id": "no-realm"})
    kv = parse_fields(SecretKind.KV, value=None, fields={"values": {"B": "x" * 8, "A": "y" * 8}})
    assert derive_metadata(SecretKind.KV, kv, {}).model_dump() == {"keys": ["A", "B"]}
    with pytest.raises(InvalidInput, match="derived"):
        derive_metadata(SecretKind.KV, kv, {"keys": ["Z"]})
    ssh = generate_ssh_key()
    with pytest.raises(InvalidInput, match="only 'comment'"):
        derive_metadata(SecretKind.SSH_KEY, ssh, {"public_key": "ssh-ed25519 AAAA"})
    with pytest.raises(InvalidInput, match="comment"):
        derive_metadata(SecretKind.SSH_KEY, ssh, {"comment": 'x" injected'})


def test_file_size_is_derived_not_trusted(kind_sample):
    _, fields, _, _ = kind_sample("file")
    parsed = parse_fields(SecretKind.FILE, value=None, fields=fields)
    meta = derive_metadata(SecretKind.FILE, parsed, {"filename": "kubeconfig", "size": 1})
    assert meta.model_dump()["size"] == len(parsed.content)


def test_carried_metadata_drops_what_the_new_value_derives():
    assert carried_metadata(SecretKind.SSH_KEY, {"public_key": "k", "comment": "c"}) == {
        "comment": "c"
    }
    assert carried_metadata(SecretKind.KV, {"keys": ["A"]}) == {}
    assert carried_metadata(SecretKind.FILE, {"filename": "f", "size": 3}) == {"filename": "f"}
    assert carried_metadata(SecretKind.PASSWORD, {"username": "u"}) == {"username": "u"}


def test_primary_value_only_for_single_value_kinds(kind_sample):
    value = str(uuid.uuid4())
    token = parse_fields(SecretKind.PROXMOX_TOKEN, value=value, fields=None)
    assert primary_value(SecretKind.PROXMOX_TOKEN, token).reveal() == value
    for kind in (SecretKind.KV, SecretKind.FILE, SecretKind.SSH_KEY):
        v, f, _, _ = kind_sample(kind.value)
        with pytest.raises(InvalidInput, match="single token value"):
            primary_value(kind, parse_fields(kind, value=v, fields=f))


def test_generated_ssh_key_is_ed25519_and_its_public_key_is_valid_openssh():
    fields = generate_ssh_key()
    assert isinstance(fields, SshKeyFields)
    assert "OPENSSH PRIVATE KEY" in fields.private_key.reveal()
    meta = fields.public_metadata(comment="deploy@harness")
    assert meta.public_key.startswith("ssh-ed25519 ")
    assert meta.public_key.endswith(" deploy@harness")
    serialization.load_ssh_public_key(meta.public_key.encode())  # parses as OpenSSH
    assert meta.fingerprint.startswith("SHA256:")
    assert generate_ssh_key().private_key != fields.private_key  # fresh each time


def test_authorized_keys_line_with_and_without_from():
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample c"
    assert authorized_keys_line(key) == key
    line = authorized_keys_line(key, from_hosts=["10.0.0.0/8", "!10.0.0.9", "*.tailnet"])
    assert line == f'from="10.0.0.0/8,!10.0.0.9,*.tailnet" {key}'
    for bad in (['a",command="sh'], ["a b"], ["x"] * 33):
        with pytest.raises(InvalidInput, match="from="):
            authorized_keys_line(key, from_hosts=bad)
