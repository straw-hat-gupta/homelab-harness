"""Validation of Proxmox identifiers before they reach a URL or a shell script.

Node names, storage IDs and pool IDs end up in API paths and in the root-run
bootstrap script, so they are checked against the formats PVE itself enforces
(``PVE::JSONSchema``) instead of being escaped after the fact. Messages never
echo the rejected value: it may be client-supplied.

Pure logic: no I/O, no framework imports.
"""

from __future__ import annotations

import re

from homelab_harness_sdk.errors import InvalidInput

_NODE = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?")
_STORAGE = re.compile(r"[a-zA-Z][a-zA-Z0-9\-_.]*[a-zA-Z0-9]")
_POOL = re.compile(r"[A-Za-z0-9.\-_]+")
_BRIDGE = re.compile(r"[a-zA-Z][a-zA-Z0-9_.]{0,20}")
_CLUSTER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,62}")
_DISK = re.compile(r"/dev/[A-Za-z0-9_.:\-/]+")
_CONTENT = re.compile(r"[a-z]+")

MIN_VMID = 100
MAX_VMID = 999_999_999


def _check(pattern: re.Pattern[str], value: str, what: str) -> str:
    if len(value) > 128 or pattern.fullmatch(value) is None:
        raise InvalidInput(f"invalid {what}")
    return value


def node_name(value: str) -> str:
    """Return ``value`` if it is a valid PVE node name.

    Raises:
        InvalidInput: If it is not.
    """
    return _check(_NODE, value, "Proxmox node name")


def storage_id(value: str) -> str:
    """Return ``value`` if it is a valid PVE storage ID.

    Raises:
        InvalidInput: If it is not.
    """
    return _check(_STORAGE, value, "Proxmox storage ID")


def pool_id(value: str) -> str:
    """Return ``value`` if it is a valid PVE pool ID.

    Raises:
        InvalidInput: If it is not.
    """
    return _check(_POOL, value, "Proxmox pool ID")


def bridge_name(value: str) -> str:
    """Return ``value`` if it is a valid Linux bridge name as PVE accepts it.

    Raises:
        InvalidInput: If it is not.
    """
    return _check(_BRIDGE, value, "bridge name")


def cluster_name(value: str) -> str:
    """Return ``value`` if it is a valid harness cluster label.

    Raises:
        InvalidInput: If it is not.
    """
    return _check(_CLUSTER, value, "cluster name")


def content_type(value: str) -> str:
    """Return ``value`` if it looks like a PVE storage content type (``images``, ``iso``).

    Raises:
        InvalidInput: If it does not.
    """
    return _check(_CONTENT, value, "storage content type")


def disk_path(value: str) -> str:
    """Return ``value`` if it is a ``/dev/...`` path with no traversal.

    Raises:
        InvalidInput: If it is not.
    """
    _check(_DISK, value, "disk device path")
    if ".." in value.split("/"):
        raise InvalidInput("invalid disk device path")
    return value


def vmid(value: int) -> int:
    """Return ``value`` if it is in PVE's VMID range.

    Raises:
        InvalidInput: If it is not.
    """
    if isinstance(value, bool) or not MIN_VMID <= value <= MAX_VMID:
        raise InvalidInput("invalid VMID")
    return value
