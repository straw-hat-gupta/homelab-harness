"""Typed views of Proxmox VE API responses.

Shapes follow the PVE API viewer (``pve-docs/api-viewer``) for 9.x. Every model
tolerates and keeps fields it does not know (``model_extra``), because PVE adds
fields between minor releases and dropping them would hide information.

PVE encodes booleans as ``0``/``1``, lists as ``;``- or ``,``-separated strings,
and times as Unix epoch seconds. The validators here normalise those so callers
get plain Python types. Text such as guest names, tags, descriptions and task
logs is target-sourced and untrusted (S7): it is carried as data, never acted on.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from homelab_harness_proxmox.upid import Upid, parse_upid

GuestType = Literal["qemu", "lxc"]


class PveModel(BaseModel):
    """Base for API views: unknown fields are kept, hyphenated names have aliases."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


def _split(value: Any, separators: str) -> Any:
    if isinstance(value, str):
        return [part for part in re.split(f"[{separators}]+", value) if part]
    return value


def _epoch(value: Any) -> Any:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=UTC)
    return value


class Listing[T](BaseModel):
    """A list read from the target, with the time it was observed.

    Attributes:
        items: The rows, in the order the API returned them.
        as_of: When the harness received the response (aware UTC).
    """

    items: list[T]
    as_of: datetime


class Version(PveModel):
    """``GET /version``."""

    version: str
    release: str
    repoid: str | None = None


class ClusterStatusEntry(PveModel):
    """One row of ``GET /cluster/status``: the cluster itself or one node."""

    type: str
    name: str
    id: str | None = None
    ip: str | None = None
    nodeid: int | None = None
    online: bool | None = None
    local: bool | None = None
    quorate: bool | None = None
    nodes: int | None = None
    version: int | None = None


class ResourceType(StrEnum):
    """Filter values for ``GET /cluster/resources?type=``."""

    VM = "vm"
    STORAGE = "storage"
    NODE = "node"
    SDN = "sdn"


class Resource(PveModel):
    """One row of ``GET /cluster/resources``: a guest, node, storage or SDN object."""

    id: str
    type: str
    node: str | None = None
    status: str | None = None
    name: str | None = None
    vmid: int | None = None
    pool: str | None = None
    tags: list[str] = Field(default_factory=list[str])
    template: bool = False
    lock: str | None = None
    hastate: str | None = None
    storage: str | None = None
    cpu: float | None = None
    maxcpu: float | None = None
    mem: int | None = None
    maxmem: int | None = None
    disk: int | None = None
    maxdisk: int | None = None
    uptime: int | None = None

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, value: Any) -> Any:
        return _split(value, ";, ")


class NodeSummary(PveModel):
    """One row of ``GET /nodes``."""

    node: str
    status: str
    cpu: float | None = None
    maxcpu: int | None = None
    mem: int | None = None
    maxmem: int | None = None
    disk: int | None = None
    maxdisk: int | None = None
    uptime: int | None = None
    level: str | None = None
    ssl_fingerprint: str | None = None


class CpuInfo(PveModel):
    """``cpuinfo`` inside node status."""

    model: str | None = None
    cpus: int | None = None
    cores: int | None = None
    sockets: int | None = None
    mhz: str | None = None


class Usage(PveModel):
    """Byte counters (memory, swap, root filesystem)."""

    total: int | None = None
    used: int | None = None
    free: int | None = None
    avail: int | None = None


class NodeStatus(PveModel):
    """``GET /nodes/{node}/status``."""

    uptime: int | None = None
    cpu: float | None = None
    cpuinfo: CpuInfo | None = None
    memory: Usage | None = None
    swap: Usage | None = None
    rootfs: Usage | None = None
    loadavg: list[str] = Field(default_factory=list[str])
    kversion: str | None = None
    pveversion: str | None = None
    as_of: datetime


class RrdTimeframe(StrEnum):
    """``timeframe`` for RRD reads."""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class RrdConsolidation(StrEnum):
    """``cf`` for RRD reads."""

    AVERAGE = "AVERAGE"
    MAX = "MAX"


class RrdPoint(PveModel):
    """One sample of ``GET /nodes/{node}/rrddata``.

    Only ``time`` is guaranteed: PVE omits metrics for intervals with no data.
    The remaining metrics (``netin``, ``iowait``, ``swapused`` …) stay in
    ``model_extra``.
    """

    time: datetime
    cpu: float | None = None
    maxcpu: float | None = None
    memused: float | None = None
    memtotal: float | None = None
    loadavg: float | None = None

    @field_validator("time", mode="before")
    @classmethod
    def _epoch_time(cls, value: Any) -> Any:
        return _epoch(value)


class Guest(PveModel):
    """One row of ``GET /nodes/{node}/qemu`` or ``/lxc``.

    ``type`` and ``node`` are filled in by the adapter: the QEMU list does not
    carry a type, and neither list carries the node it was read from.
    """

    vmid: int
    type: GuestType
    node: str
    status: str
    name: str | None = None
    tags: list[str] = Field(default_factory=list[str])
    lock: str | None = None
    template: bool = False
    cpus: float | None = None
    maxmem: int | None = None
    maxdisk: int | None = None
    uptime: int | None = None

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, value: Any) -> Any:
        return _split(value, ";, ")


class GuestConfig(BaseModel):
    """``GET /nodes/{node}/{qemu|lxc}/{vmid}/config``.

    Attributes:
        raw: The full config exactly as returned. It can contain sensitive keys
            (``cipassword``, ``sshkeys``); tools must redact before returning it (§9).
        digest: SHA-1 of the config file; pass it back on writes for optimistic
            concurrency (§3).
    """

    vmid: int
    type: GuestType
    node: str
    digest: str
    raw: dict[str, Any]
    name: str | None = None
    tags: list[str] = Field(default_factory=list[str])
    lock: str | None = None
    template: bool = False

    @classmethod
    def from_api(
        cls, *, vmid: int, type: GuestType, node: str, data: dict[str, Any]
    ) -> GuestConfig:
        """Build from the API ``data`` object.

        Args:
            vmid: Guest ID the config was read for.
            type: ``qemu`` or ``lxc``.
            node: Node it was read from.
            data: The ``data`` object of the response.

        Returns:
            The typed config; ``raw`` holds every key.
        """
        return cls(
            vmid=vmid,
            type=type,
            node=node,
            digest=data["digest"],
            raw=data,
            # LXC calls the guest's name "hostname".
            name=data.get("name") or data.get("hostname"),
            tags=_split(data.get("tags", ""), ";, "),
            lock=data.get("lock"),
            template=bool(data.get("template", 0)),
        )


class GuestStatus(PveModel):
    """``GET /nodes/{node}/{qemu|lxc}/{vmid}/status/current``."""

    vmid: int
    status: str
    name: str | None = None
    qmpstatus: str | None = None
    lock: str | None = None
    uptime: int | None = None
    cpu: float | None = None
    mem: int | None = None
    maxmem: int | None = None
    ha: dict[str, Any] = Field(default_factory=dict[str, Any])
    tags: list[str] = Field(default_factory=list[str])
    as_of: datetime

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, value: Any) -> Any:
        return _split(value, ";, ")


class StorageConfig(PveModel):
    """One row of ``GET /storage`` (datacenter storage configuration)."""

    storage: str
    type: str
    content: list[str] = Field(default_factory=list[str])
    shared: bool = False
    disable: bool = False
    nodes: list[str] | None = None
    digest: str | None = None

    @field_validator("content", "nodes", mode="before")
    @classmethod
    def _lists(cls, value: Any) -> Any:
        return _split(value, ",")


class StorageStatus(PveModel):
    """``GET /nodes/{node}/storage/{storage}/status``."""

    type: str
    content: list[str] = Field(default_factory=list[str])
    active: bool = False
    enabled: bool = True
    shared: bool = False
    total: int | None = None
    used: int | None = None
    avail: int | None = None
    as_of: datetime

    @field_validator("content", mode="before")
    @classmethod
    def _lists(cls, value: Any) -> Any:
        return _split(value, ",")


class StorageVolume(PveModel):
    """One row of ``GET /nodes/{node}/storage/{storage}/content``."""

    volid: str
    content: str
    format: str | None = None
    size: int | None = None
    used: int | None = None
    vmid: int | None = None
    ctime: datetime | None = None
    notes: str | None = None
    protected: bool = False

    @field_validator("ctime", mode="before")
    @classmethod
    def _epoch_ctime(cls, value: Any) -> Any:
        return _epoch(value)


class Disk(PveModel):
    """One row of ``GET /nodes/{node}/disks/list``.

    Attributes:
        wearout: Remaining endurance in percent; ``None`` when PVE reports ``N/A``.
        used: What occupies the disk (``ZFS``, ``LVM``, ``partitions``, ``mounted`` …);
            ``None`` means PVE found nothing on it.
        by_id_link: Stable ``/dev/disk/by-id`` path. The field name is from the API
            viewer and is *(unverified)* on a live 9.2 node.
    """

    devpath: str
    type: str | None = None
    size: int | None = None
    model: str | None = None
    serial: str | None = None
    vendor: str | None = None
    wwn: str | None = None
    health: str | None = None
    wearout: int | None = None
    used: str | None = None
    gpt: bool = False
    parent: str | None = None
    by_id_link: str | None = None

    @field_validator("wearout", mode="before")
    @classmethod
    def _wearout(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.isdigit() else value


class SmartAttribute(PveModel):
    """One ATA SMART attribute row."""

    id: int | str
    name: str
    value: int | str | None = None
    worst: int | str | None = None
    threshold: int | str | None = None
    raw: str | None = None
    flags: str | None = None
    fail: str | None = None


class SmartData(PveModel):
    """``GET /nodes/{node}/disks/smart``.

    ATA disks report ``attributes``; NVMe and SAS disks report free ``text`` instead.
    """

    health: str
    type: str | None = None
    attributes: list[SmartAttribute] = Field(default_factory=list[SmartAttribute])
    text: str | None = None


class NetworkInterface(PveModel):
    """One row of ``GET /nodes/{node}/network``."""

    iface: str
    type: str
    active: bool = False
    autostart: bool = False
    method: str | None = None
    method6: str | None = None
    address: str | None = None
    netmask: str | None = None
    cidr: str | None = None
    gateway: str | None = None
    bridge_ports: str | None = None
    families: list[str] = Field(default_factory=list[str])
    comments: str | None = None


class NetworkConfig(BaseModel):
    """``GET /nodes/{node}/network`` as a whole.

    Attributes:
        interfaces: Interfaces and bridges as currently staged.
        pending_changes: Diff of ``/etc/network/interfaces`` vs ``interfaces.new``
            when changes are staged but not applied. The top-level ``changes``
            key is *(unverified)* on a live 9.2 node.
        as_of: When the response was received.
    """

    interfaces: list[NetworkInterface]
    pending_changes: str | None
    as_of: datetime


class PoolMember(PveModel):
    """A guest or storage in a resource pool."""

    id: str
    type: str
    node: str | None = None
    vmid: int | None = None
    storage: str | None = None


class Pool(PveModel):
    """One row of ``GET /pools``; ``members`` is present when filtered by ``poolid``."""

    poolid: str
    comment: str | None = None
    members: list[PoolMember] = Field(default_factory=list[PoolMember])


class Task(PveModel):
    """One row of ``GET /nodes/{node}/tasks`` or ``GET /cluster/tasks``."""

    upid: str
    node: str
    type: str
    user: str
    id: str | None = None
    status: str | None = None
    starttime: datetime
    endtime: datetime | None = None

    @field_validator("starttime", "endtime", mode="before")
    @classmethod
    def _epoch_times(cls, value: Any) -> Any:
        return _epoch(value)

    @property
    def parsed_upid(self) -> Upid:
        """The decoded UPID (raises ``InvalidInput`` if PVE sent a malformed one)."""
        return parse_upid(self.upid)


class TaskOutcome(StrEnum):
    """How a task ended, derived from ``status`` and ``exitstatus`` (§3)."""

    RUNNING = "running"
    OK = "ok"
    WARNINGS = "warnings"
    FAILED = "failed"


class TaskStatus(PveModel):
    """``GET /nodes/{node}/tasks/{upid}/status``."""

    upid: str
    node: str
    status: str
    type: str
    user: str
    id: str | None = None
    exitstatus: str | None = None
    starttime: datetime | None = None

    @field_validator("starttime", mode="before")
    @classmethod
    def _epoch_start(cls, value: Any) -> Any:
        return _epoch(value)

    @property
    def outcome(self) -> TaskOutcome:
        """``OK`` is success, ``WARNINGS: n`` is success with warnings, anything else failed."""
        if self.status != "stopped":
            return TaskOutcome.RUNNING
        if self.exitstatus == "OK":
            return TaskOutcome.OK
        if self.exitstatus is not None and self.exitstatus.startswith("WARNINGS"):
            return TaskOutcome.WARNINGS
        return TaskOutcome.FAILED


class TaskLogLine(PveModel):
    """One line of a task log: ``n`` is the 1-based line number, ``t`` the text."""

    n: int
    t: str


class TaskLog(BaseModel):
    """A window of ``GET /nodes/{node}/tasks/{upid}/log``.

    Attributes:
        lines: The returned lines (untrusted target text).
        total: Total line count PVE reports, for incremental reads.
    """

    lines: list[TaskLogLine]
    total: int | None


class HaStatusEntry(PveModel):
    """One row of ``GET /cluster/ha/status/current`` (quorum, master, lrm or service)."""

    id: str
    type: str
    node: str | None = None
    status: str | None = None
    quorate: bool | None = None
    sid: str | None = None
    state: str | None = None
    crm_state: str | None = None
    request_state: str | None = None


class BackupJob(PveModel):
    """One row of ``GET /cluster/backup``."""

    id: str
    type: str | None = None
    schedule: str | None = None
    enabled: bool = True
    storage: str | None = None
    node: str | None = None
    vmid: list[str] = Field(default_factory=list[str])
    all: bool = False
    pool: str | None = None
    mode: str | None = None
    compress: str | None = None
    comment: str | None = None
    next_run: datetime | None = Field(default=None, alias="next-run")

    @field_validator("next_run", mode="before")
    @classmethod
    def _epoch_next(cls, value: Any) -> Any:
        return _epoch(value)

    @field_validator("vmid", mode="before")
    @classmethod
    def _vmids(cls, value: Any) -> Any:
        return _split(value, ",") if isinstance(value, str) else value
