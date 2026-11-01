"""Guest config masking (§9): pure-logic tests with runtime canaries."""

import base64
import hashlib
from urllib.parse import quote

import pytest

from homelab_harness_proxmox.masking import MASK, mask_guest_config, ssh_key_fingerprints

BLOB = base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519" + bytes(range(32))).decode()
FINGERPRINT = "SHA256:" + base64.b64encode(hashlib.sha256(base64.b64decode(BLOB)).digest()).decode()


def test_fingerprints_are_openssh_sha256_and_drop_comments(canary_secret):
    encoded = quote(f'ssh-ed25519 {BLOB} {canary_secret}\nfrom="x" ssh-ed25519 {BLOB} c2\n')
    assert ssh_key_fingerprints(encoded) == [FINGERPRINT.rstrip("="), FINGERPRINT.rstrip("=")]


def test_unparseable_ssh_lines_are_skipped():
    assert ssh_key_fingerprints(quote("not a key\n\n")) == []


@pytest.mark.parametrize(
    "key",
    ["cipassword", "args", "hookscript", "cicustom", "apitoken", "MY_SECRET", "ipmi_key", "passwd"],
)
def test_sensitive_values_are_masked(key, canary_secret):
    masked = mask_guest_config({key: f"x {canary_secret} y", "cores": 2, "digest": "d"})
    assert masked.values[key] == MASK
    assert masked.masked_keys == [key]
    assert canary_secret not in repr(masked)
    assert masked.values["cores"] == 2


def test_sshkeys_become_fingerprints_and_shown_fields_are_left_out(canary_secret):
    raw = {
        "sshkeys": quote(f"ssh-ed25519 {BLOB} {canary_secret}"),
        "name": "web-01",
        "description": "notes",
        "tags": "a;b",
        "digest": "abc",
        "net0": "virtio=BC:24:11:00:00:01,bridge=vmbr0",
    }
    masked = mask_guest_config(raw)
    assert masked.values == {"sshkeys": MASK, "net0": raw["net0"]}
    assert masked.ssh_key_fingerprints == [FINGERPRINT.rstrip("=")]
    assert canary_secret not in repr(masked)
