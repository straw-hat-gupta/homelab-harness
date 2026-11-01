"""UPID parser: decoding, canonical round-trip, and rejection of malformed input."""

import random
from datetime import UTC, datetime

import pytest

from homelab_harness_proxmox import Upid, parse_upid
from homelab_harness_sdk.errors import InvalidInput


def test_decodes_every_field():
    upid = parse_upid("UPID:pve1:0001A2B3:00C4D5E6:6720F3A1:qmstart:101:harness@pve!guest-ops:")
    assert upid == Upid(
        node="pve1",
        pid=0x1A2B3,
        pstart=0xC4D5E6,
        starttime=datetime(2024, 10, 29, 14, 39, 29, tzinfo=UTC),
        type="qmstart",
        id="101",
        user="harness@pve!guest-ops",
    )


@pytest.mark.parametrize(
    "text",
    [
        "UPID:pve1:0001A2B3:00C4D5E6:6720F3A1:qmstart:101:harness@pve!guest-ops:",
        "UPID:pve2:0002B3C4:00D5E6F7:6720F000:vzdump::root@pam:",  # node-wide: empty id
        "UPID:node-a1:00000001:1C4D5E6F7:6720F000:aptupdate::root@pam:",  # 9-digit pstart
    ],
)
def test_canonical_strings_round_trip(text):
    assert str(parse_upid(text)) == text


def test_random_fields_round_trip():
    rng = random.Random(1234)  # noqa: S311 - deterministic test data, not crypto
    for _ in range(200):
        upid = Upid(
            node=rng.choice(["pve", "pve1", "node-7", "a"]),
            pid=rng.randrange(0, 2**32),
            pstart=rng.randrange(0, 2**36),
            starttime=datetime.fromtimestamp(rng.randrange(0, 2**32), tz=UTC),
            type=rng.choice(["qmstart", "vzdump", "qmigrate", "zfscreate"]),
            id=rng.choice(["", "100", "999999999", "local-zfs"]),
            user=rng.choice(["root@pam", "harness@pve!read"]),
        )
        assert parse_upid(str(upid)) == upid


def test_lower_case_hex_is_accepted():
    assert parse_upid("UPID:pve1:0001a2b3:00c4d5e6:6720f3a1:qmstart:101:root@pam:").pid == 0x1A2B3


@pytest.mark.parametrize(
    "text",
    [
        "",
        "UPID:pve1:0001A2B3:00C4D5E6:6720F3A1:qmstart:101:root@pam",  # no trailing colon
        "upid:pve1:0001A2B3:00C4D5E6:6720F3A1:qmstart:101:root@pam:",  # prefix case
        "UPID:pve1:1A2B3:00C4D5E6:6720F3A1:qmstart:101:root@pam:",  # short pid
        "UPID:pve1:0001A2B3:00C4D5E6:6720F3A1:qmstart:101::",  # no user
        "UPID:pve1:0001A2B3:00C4D5E6:6720F3A1::101:root@pam:",  # no type
        "UPID:-pve1:0001A2B3:00C4D5E6:6720F3A1:qmstart:101:root@pam:",  # bad node
        "UPID:pve1:0001A2B3:00C4D5E6:6720F3A1:qm start:101:root@pam:",  # whitespace
        "UPID:../x:0001A2B3:00C4D5E6:6720F3A1:qmstart:101:root@pam:",  # traversal
        "UPID:pve1:0001A2B3:00C4D5E6:6720F3A1:qmstart:101:root@pam:\n",
        "UPID:pve1:GGGGGGGG:00C4D5E6:6720F3A1:qmstart:101:root@pam:",
    ],
)
def test_malformed_upids_are_rejected_without_echo(text):
    with pytest.raises(InvalidInput) as raised:
        parse_upid(text)
    assert "pve1" not in raised.value.safe_message
