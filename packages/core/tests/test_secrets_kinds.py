import base64
import json
import os
import pickle
import shutil
import subprocess
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from pydantic import ValidationError

from homelab_harness.redaction import MASK, redactor
from homelab_harness.secrets.crypto import SecretIntegrityError, seal, unseal
from homelab_harness.secrets.keys import generate_kek
from homelab_harness.secrets.kinds import (
    KIND_MODELS,
    MAX_FILE_BYTES,
    ApiTokenMetadata,
    CloudflareTokenFields,
    FileFields,
    GithubTokenFields,
    KvFields,
    PasswordFields,
    ProxmoxTokenFields,
    ProxmoxTokenMetadata,
    SecretBytes,
    SecretKind,
    SecretValue,
    SshKeyFields,
    SshKeyMetadata,
    TokenFields,
    decode_fields,
    encode_fields,
)


def _canary(label):
    return f"hh-canary-{label}-{os.urandom(8).hex()}"


def _openssh_key(key=None, passphrase=None):
    key = key or ed25519.Ed25519PrivateKey.generate()
    encryption = (
        serialization.BestAvailableEncryption(passphrase.encode())
        if passphrase
        else serialization.NoEncryption()
    )
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, encryption
    ).decode()


def _pem_key(key, passphrase=None):
    encryption = (
        serialization.BestAvailableEncryption(passphrase.encode())
        if passphrase
        else serialization.NoEncryption()
    )
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption
    ).decode()


def _examples():
    return {
        SecretKind.SSH_KEY: SshKeyFields(private_key=_openssh_key()),
        SecretKind.PASSWORD: PasswordFields(password=_canary("pw")),
        SecretKind.API_TOKEN: TokenFields(token=_canary("api")),
        SecretKind.PROXMOX_TOKEN: ProxmoxTokenFields(secret=str(uuid.uuid4())),
        SecretKind.CLOUDFLARE_TOKEN: CloudflareTokenFields(token=_canary("cf")),
        SecretKind.GITHUB_TOKEN: GithubTokenFields(token=_canary("gh")),
        SecretKind.FILE: FileFields(content=os.urandom(4096)),
        SecretKind.KV: KvFields(values={"DB_USER": _canary("kv1"), "db.pass": _canary("kv2")}),
    }


def test_every_kind_has_an_example():
    assert set(_examples()) == set(KIND_MODELS) == set(SecretKind)


@pytest.mark.parametrize("kind", list(SecretKind))
def test_round_trip_through_seal_and_unseal(kind):
    fields = _examples()[kind]
    assert fields.kind is kind
    kek = generate_kek("kek-1")
    sealed = seal(encode_fields(fields), secret_id="s1", version=1, kind=kind, kek=kek)
    restored = decode_fields(kind, unseal(sealed, kek=kek))
    assert type(restored) is type(fields)
    assert restored == fields


def test_decoding_under_the_wrong_kind_raises_integrity_error():
    payload = encode_fields(PasswordFields(password=_canary("pw")))
    with pytest.raises(SecretIntegrityError, match="does not match kind"):
        decode_fields(SecretKind.FILE, payload)


def test_decrypted_canary_is_masked_by_the_redactor():
    CANARY_TOKEN = _canary("decrypt")
    kek = generate_kek("kek-1")
    plaintext = json.dumps({"token": CANARY_TOKEN}).encode()
    sealed = seal(plaintext, secret_id="s1", version=1, kind="api_token", kek=kek)
    assert CANARY_TOKEN in redactor.scrub_text(f"before {CANARY_TOKEN}")
    decode_fields(SecretKind.API_TOKEN, unseal(sealed, kek=kek))
    out = redactor.scrub_text(
        f"leaked {CANARY_TOKEN} and {base64.b64encode(CANARY_TOKEN.encode())}"
    )
    assert CANARY_TOKEN not in out
    assert MASK in out


def test_secret_value_never_reveals_itself():
    CANARY_TOKEN = _canary("wrap")
    fields = TokenFields(token=CANARY_TOKEN)
    surfaces = [
        repr(fields.token),
        str(fields.token),
        f"{fields.token}",
        f"{fields.token!r:>40}",
        "%s" % fields.token,  # noqa: UP031
        repr(fields),
        str(fields),
        str(fields.model_dump()),
        fields.model_dump_json(),
        json.dumps(fields.model_dump(mode="json")),
        str(fields.model_dump(context={"reveal": True})),
    ]
    for text in surfaces:
        assert CANARY_TOKEN not in text
    assert repr(fields.token) == "SecretValue(***)"
    assert fields.model_dump() == {"token": "***"}
    assert fields.token.reveal() == CANARY_TOKEN
    with pytest.raises(TypeError, match="pickled"):
        pickle.dumps(fields.token)


def test_secret_bytes_never_reveal_themselves():
    CANARY_FILE = _canary("file").encode()
    fields = FileFields(content=CANARY_FILE)
    encoded = base64.b64encode(CANARY_FILE).decode()
    for text in (repr(fields), str(fields.model_dump()), fields.model_dump_json()):
        assert CANARY_FILE.decode() not in text
        assert encoded not in text
    assert repr(fields.content) == "SecretBytes(***)"
    assert len(fields.content) == len(CANARY_FILE)
    assert isinstance(fields.content, SecretBytes)


def test_validation_errors_do_not_echo_the_input():
    CANARY_TOKEN = _canary("bad-proxmox")
    with pytest.raises(ValidationError) as info:
        ProxmoxTokenFields(secret=CANARY_TOKEN)
    assert CANARY_TOKEN not in str(info.value)
    assert "must be a UUID" in str(info.value)


def test_secret_values_compare_by_content():
    assert SecretValue("hh-canary-same-1") == SecretValue("hh-canary-same-1")
    assert SecretValue("hh-canary-same-1") != SecretValue("hh-canary-same-2")


@pytest.mark.parametrize(
    "token_id", ["harness@pve!read", "root@pam!hh-ops_1", "svc.bot@ldap-corp!t.1"]
)
def test_proxmox_token_id_accepts_user_realm_tokenid(token_id):
    assert ProxmoxTokenMetadata(token_id=token_id).token_id == token_id


@pytest.mark.parametrize(
    "token_id", ["harness@pve", "harness!read", "@pve!read", "harness@pve!1read", "a b@pve!x"]
)
def test_proxmox_token_id_rejects_other_shapes(token_id):
    with pytest.raises(ValidationError):
        ProxmoxTokenMetadata(token_id=token_id)


def test_api_token_header_scheme_needs_a_header_name():
    assert ApiTokenMetadata(scheme="header", header_name="X-Api-Key").header_name == "X-Api-Key"
    with pytest.raises(ValidationError):
        ApiTokenMetadata(scheme="header")
    with pytest.raises(ValidationError):
        ApiTokenMetadata(scheme="bearer", header_name="X-Api-Key")


def test_api_token_base_urls_must_not_embed_credentials():
    with pytest.raises(ValidationError, match="embed credentials"):
        ApiTokenMetadata(allowed_base_urls=["https://user:pw@api.example.com"])


def test_file_size_is_limited():
    FileFields(content=b"\x00" * MAX_FILE_BYTES)
    with pytest.raises(ValidationError, match="limited"):
        FileFields(content=b"\x00" * (MAX_FILE_BYTES + 1))


def test_kv_key_names_are_validated_and_listed():
    fields = KvFields(values={"b_key": _canary("b"), "A": _canary("a")})
    assert fields.key_names() == ["A", "b_key"]
    with pytest.raises(ValidationError):
        KvFields(values={"has space": _canary("c")})
    with pytest.raises(ValidationError):
        KvFields(values={})


def test_ssh_ed25519_metadata_and_fingerprint_format():
    key = ed25519.Ed25519PrivateKey.generate()
    meta = SshKeyFields(private_key=_openssh_key(key)).public_metadata(comment="hh@docker-01")
    assert isinstance(meta, SshKeyMetadata)
    assert meta.public_key.startswith("ssh-ed25519 ")
    assert meta.public_key.endswith(" hh@docker-01")
    assert meta.fingerprint.startswith("SHA256:")
    assert len(meta.fingerprint) == len("SHA256:") + 43
    assert not meta.fingerprint.endswith("=")


NO_SSH_KEYGEN = shutil.which("ssh-keygen") is None


@pytest.mark.skipif(NO_SSH_KEYGEN, reason="ssh-keygen not installed")
@pytest.mark.parametrize(
    "make_key",
    [
        ed25519.Ed25519PrivateKey.generate,
        lambda: ec.generate_private_key(ec.SECP256R1()),
        lambda: rsa.generate_private_key(public_exponent=65537, key_size=2048),
    ],
    ids=["ed25519", "ecdsa", "rsa"],
)
def test_ssh_fingerprint_matches_ssh_keygen(tmp_path, make_key):
    key = make_key()
    meta = SshKeyFields(private_key=_pem_key(key)).public_metadata()
    pub = tmp_path / "key.pub"
    pub.write_text(meta.public_key + "\n")
    out = subprocess.run(  # noqa: S603
        ["ssh-keygen", "-l", "-E", "sha256", "-f", str(pub)],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.split()[1] == meta.fingerprint


def test_ssh_key_with_passphrase():
    PASSPHRASE_CANARY = _canary("passphrase")
    pem = _pem_key(ed25519.Ed25519PrivateKey.generate(), passphrase=PASSPHRASE_CANARY)
    fields = SshKeyFields(private_key=pem, passphrase=PASSPHRASE_CANARY)
    assert fields.public_metadata().fingerprint.startswith("SHA256:")
    with pytest.raises(ValidationError, match="could not be loaded") as info:
        SshKeyFields(private_key=pem, passphrase=_canary("wrong"))
    assert PASSPHRASE_CANARY not in str(info.value)
    with pytest.raises(ValidationError, match="could not be loaded"):
        SshKeyFields(private_key=pem)


@pytest.mark.skipif(NO_SSH_KEYGEN, reason="ssh-keygen not installed")
def test_passphrase_protected_openssh_keys_are_refused_clearly(tmp_path):
    # Decrypting OpenSSH-format keys needs the bcrypt KDF, which is not installed.
    PASSPHRASE_CANARY = _canary("pp")
    path = tmp_path / "id"
    subprocess.run(  # noqa: S603
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", PASSPHRASE_CANARY, "-f", str(path)],  # noqa: S607
        check=True,
    )
    with pytest.raises(ValidationError, match="not supported") as info:
        SshKeyFields(private_key=path.read_text(), passphrase=PASSPHRASE_CANARY)
    assert PASSPHRASE_CANARY not in str(info.value)


def test_ssh_key_rejects_non_keys():
    with pytest.raises(ValidationError, match="could not be loaded"):
        SshKeyFields(private_key="not a key at all")
