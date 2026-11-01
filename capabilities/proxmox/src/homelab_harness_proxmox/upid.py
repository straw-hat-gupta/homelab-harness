"""Parse and encode Proxmox task identifiers (UPIDs).

A UPID names one asynchronous task on one node. PVE encodes it as
``UPID:<node>:<pid hex>:<pstart hex>:<starttime hex>:<type>:<id>:<user>:``
(``PVE::Tools::upid_encode``). The node is load-bearing: a task's status and
log can only be read from the node that runs it, so callers route by
``Upid.node``.

Pure logic: no I/O, no framework imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from homelab_harness_sdk.errors import InvalidInput

# Mirrors the decoder regex in PVE::Tools::upid_decode. pstart may need nine hex
# digits on long-running hosts, so it is the one field allowed to grow.
_UPID = re.compile(
    r"^UPID:"
    r"(?P<node>[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?):"
    r"(?P<pid>[0-9A-Fa-f]{8}):"
    r"(?P<pstart>[0-9A-Fa-f]{8,9}):"
    r"(?P<starttime>[0-9A-Fa-f]{8}):"
    r"(?P<type>[^:\s]+):"
    r"(?P<id>[^:\s]*):"
    r"(?P<user>[^:\s]+):$"
)


@dataclass(frozen=True, slots=True)
class Upid:
    """A decoded Proxmox task identifier.

    Attributes:
        node: Node that runs the task; status and log reads must go there.
        pid: Worker process ID on that node.
        pstart: Process start time in clock ticks since boot (disambiguates PID reuse).
        starttime: When the task started, aware UTC.
        type: Task type, for example ``qmstart`` or ``vzdump``.
        id: Task object, usually a VMID; empty for node-wide tasks.
        user: Who started it, for example ``harness@pve!guest-ops``.
    """

    node: str
    pid: int
    pstart: int
    starttime: datetime
    type: str
    id: str
    user: str

    def __str__(self) -> str:
        """Encode in the canonical PVE form (upper-case, zero-padded hex)."""
        return (
            f"UPID:{self.node}:{self.pid:08X}:{self.pstart:08X}:"
            f"{int(self.starttime.timestamp()):08X}:{self.type}:{self.id}:{self.user}:"
        )


def parse_upid(text: str) -> Upid:
    """Decode a UPID string.

    Args:
        text: The UPID as returned by the Proxmox API.

    Returns:
        The decoded identifier.

    Raises:
        InvalidInput: If ``text`` is not a well-formed UPID. The message does
            not echo the input, which may be client-supplied.
    """
    match = _UPID.fullmatch(text)
    if match is None:
        raise InvalidInput("not a valid Proxmox task identifier (UPID)")
    return Upid(
        node=match["node"],
        pid=int(match["pid"], 16),
        pstart=int(match["pstart"], 16),
        starttime=datetime.fromtimestamp(int(match["starttime"], 16), tz=UTC),
        type=match["type"],
        id=match["id"],
        user=match["user"],
    )
