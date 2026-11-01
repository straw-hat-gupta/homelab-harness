"""Arguments and results of the Proxmox read tools (§4.1): the MCP-facing schemas.

These are separate from the adapter models on purpose. The adapter keeps every
field PVE sends; a tool result is a stable, documented shape in which
target-sourced text (guest names, tags, descriptions, notes, comments, task
status text and logs, SMART text) sits inside an ``untrusted`` envelope (S7),
and guest config arrives masked (§9).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from homelab_harness_proxmox.masking import ConfigValue
from homelab_harness_proxmox.models import RrdConsolidation, RrdTimeframe
from homelab_harness_sdk import ToolInput, ToolOutput, Untrusted

GuestKind = Literal["qemu", "lxc"]
TaskOutcomeName = Literal["running", "ok", "warnings", "failed"]

_CLUSTER = Field(
    default=None,
    description="Registered cluster name; may be omitted when only one is registered.",
    max_length=63,
)
_NODE = Field(description="Node name, as in proxmox.node.list.", min_length=1, max_length=63)


# -- inputs ------------------------------------------------------------------------------


class ClusterArgs(ToolInput):
    """Arguments of tools that read one cluster as a whole."""

    cluster: str | None = _CLUSTER


class AllClustersArgs(ToolInput):
    """Arguments of ``proxmox.cluster.list``."""

    cluster: str | None = Field(
        default=None, description="Only this registered cluster; all of them when omitted."
    )


class ResourcesArgs(ToolInput):
    """Arguments of ``proxmox.cluster.resources``."""

    cluster: str | None = _CLUSTER
    type: Literal["vm", "storage", "node", "sdn"] | None = Field(
        default=None, description="Only resources of this type."
    )
    node: str | None = Field(default=None, description="Only resources on this node.")
    pool: str | None = Field(default=None, description="Only resources in this pool.")
    tag: str | None = Field(default=None, description="Only guests carrying this tag.")


class NodeArgs(ToolInput):
    """Arguments of tools that read one node."""

    cluster: str | None = _CLUSTER
    node: str = _NODE


class GuestListArgs(ToolInput):
    """Arguments of ``proxmox.guest.list``."""

    cluster: str | None = _CLUSTER
    node: str | None = Field(default=None, description="Only guests on this node.")
    type: GuestKind | None = Field(default=None, description="Only VMs (qemu) or containers (lxc).")


class GuestGetArgs(ToolInput):
    """Arguments of ``proxmox.guest.get``."""

    cluster: str | None = _CLUSTER
    vmid: int = Field(description="Guest ID.", ge=100, le=999_999_999)
    node: str | None = Field(
        default=None, description="Node the guest is on; looked up when omitted."
    )
    type: GuestKind | None = Field(default=None, description="qemu or lxc; looked up when omitted.")


class StorageArgs(ToolInput):
    """Arguments of tools that read one storage on one node."""

    cluster: str | None = _CLUSTER
    node: str = _NODE
    storage: str = Field(description="Storage ID, as in proxmox.storage.list.", max_length=128)


class StorageContentArgs(StorageArgs):
    """Arguments of ``proxmox.storage.content``."""

    content: str | None = Field(
        default=None, description="Only this content type: images, rootdir, backup, iso …"
    )


class DiskSmartArgs(ToolInput):
    """Arguments of ``proxmox.disk.smart``."""

    cluster: str | None = _CLUSTER
    node: str = _NODE
    disk: str = Field(description="Device path, for example /dev/sda.", max_length=128)


class PoolArgs(ToolInput):
    """Arguments of ``proxmox.pool.list``."""

    cluster: str | None = _CLUSTER
    pool: str | None = Field(default=None, description="Only this pool, with its members.")


class TaskListArgs(ToolInput):
    """Arguments of ``proxmox.task.list``."""

    cluster: str | None = _CLUSTER
    node: str | None = Field(
        default=None, description="Read this node's task history; recent cluster tasks if omitted."
    )
    type: str | None = Field(
        default=None, description="Only tasks of this type, for example vzdump or qmstart."
    )
    vmid: int | None = Field(default=None, description="Only tasks about this guest.", ge=100)
    limit: int = Field(default=50, ge=1, le=500, description="At most this many tasks.")


class TaskGetArgs(ToolInput):
    """Arguments of ``proxmox.task.get``."""

    cluster: str | None = _CLUSTER
    upid: str = Field(description="Task UPID, as in proxmox.task.list.", max_length=512)
    log_start: int = Field(default=0, ge=0, description="First log line to return (0-based).")
    log_limit: int = Field(default=50, ge=0, le=500, description="Log lines to return; 0 for none.")


class RrdArgs(ToolInput):
    """Arguments of ``proxmox.metrics.rrd``."""

    cluster: str | None = _CLUSTER
    node: str = _NODE
    timeframe: RrdTimeframe = Field(default=RrdTimeframe.HOUR, description="Window to read.")
    cf: RrdConsolidation = Field(default=RrdConsolidation.AVERAGE, description="Consolidation.")


# -- untrusted envelopes -----------------------------------------------------------------


class GuestText(Untrusted):
    """Guest-writable labels."""

    name: str | None
    tags: list[str]


class GuestConfigText(Untrusted):
    """A guest's config: values are written by anyone with config access."""

    name: str | None
    tags: list[str]
    description: str | None
    config: dict[str, ConfigValue] = Field(
        description="Config keys and values; secret-bearing values are '[MASKED]'."
    )


class NotesText(Untrusted):
    """Free-text notes or comments."""

    notes: str | None


class TaskText(Untrusted):
    """A task's status text and log lines, as the target wrote them."""

    exitstatus: str | None
    log: list[str]


class TaskRowText(Untrusted):
    """A task's status text: ``OK``, ``WARNINGS: n`` or an error message."""

    status: str | None


class SmartText(Untrusted):
    """SMART report text (NVMe and SAS disks report text instead of attributes)."""

    text: str | None


class NetworkText(Untrusted):
    """Staged, unapplied network changes as a diff."""

    pending_changes: str | None


# -- outputs -----------------------------------------------------------------------------


class Row(BaseModel):
    """Base for result rows: frozen, and no undeclared fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ClusterNodeRow(Row):
    """A node as ``/cluster/status`` reports it."""

    name: str
    nodeid: int | None
    ip: str | None
    online: bool | None


class ClusterSummary(Row):
    """One registered cluster: quorum, nodes and version, or why it could not be read."""

    cluster: str = Field(description="Registered cluster name (the harness's label).")
    reachable: bool
    error: str | None = Field(description="Owner-safe reason when unreachable.")
    pve_cluster_name: str | None
    quorate: bool | None
    version: str | None
    nodes: list[ClusterNodeRow]


class ClusterListResult(ToolOutput):
    """Result of ``proxmox.cluster.list``."""

    clusters: list[ClusterSummary]


class ResourceRow(Row):
    """A guest, node, storage or SDN object with usage."""

    id: str
    type: str
    node: str | None
    status: str | None
    vmid: int | None
    pool: str | None
    template: bool
    lock: str | None
    hastate: str | None
    storage: str | None
    cpu: float | None
    maxcpu: float | None
    mem: int | None
    maxmem: int | None
    disk: int | None
    maxdisk: int | None
    uptime: int | None
    untrusted: GuestText


class ResourcesResult(ToolOutput):
    """Result of ``proxmox.cluster.resources``."""

    cluster: str
    resources: list[ResourceRow]


class NodeRow(Row):
    """A node with online status and usage."""

    node: str
    status: str
    cpu: float | None
    maxcpu: int | None
    mem: int | None
    maxmem: int | None
    disk: int | None
    maxdisk: int | None
    uptime: int | None
    ssl_fingerprint: str | None


class NodeListResult(ToolOutput):
    """Result of ``proxmox.node.list``."""

    cluster: str
    nodes: list[NodeRow]


class UsageView(Row):
    """Byte counters."""

    total: int | None
    used: int | None
    free: int | None


class NodeResult(ToolOutput):
    """Result of ``proxmox.node.get``."""

    cluster: str
    node: str
    uptime: int | None
    cpu: float | None
    cpu_model: str | None
    cpus: int | None
    sockets: int | None
    memory: UsageView | None
    swap: UsageView | None
    rootfs: UsageView | None
    loadavg: list[str]
    kernel: str | None
    pve_version: str | None


class GuestRow(Row):
    """A guest summary."""

    vmid: int
    type: GuestKind
    node: str
    status: str
    lock: str | None
    template: bool
    cpus: float | None
    maxmem: int | None
    maxdisk: int | None
    uptime: int | None
    untrusted: GuestText


class GuestListResult(ToolOutput):
    """Result of ``proxmox.guest.list``."""

    cluster: str
    guests: list[GuestRow]
    unreachable_nodes: list[str] = Field(
        description="Nodes listed as online whose guests could not be read."
    )


class GuestResult(ToolOutput):
    """Result of ``proxmox.guest.get``: status plus masked config."""

    cluster: str
    vmid: int
    type: GuestKind
    node: str
    status: str
    qmpstatus: str | None
    lock: str | None
    template: bool
    uptime: int | None
    cpu: float | None
    mem: int | None
    maxmem: int | None
    ha_managed: bool
    ha_state: str | None
    digest: str = Field(description="Config digest; plans pass it back for optimistic locking.")
    masked_keys: list[str] = Field(description="Config keys whose values were masked.")
    ssh_key_fingerprints: list[str]
    untrusted: GuestConfigText


class StorageRow(Row):
    """A datacenter storage definition."""

    storage: str
    type: str
    content: list[str]
    shared: bool
    disabled: bool
    nodes: list[str] | None


class StorageListResult(ToolOutput):
    """Result of ``proxmox.storage.list``."""

    cluster: str
    storages: list[StorageRow]


class StorageStatusResult(ToolOutput):
    """Result of ``proxmox.storage.status``."""

    cluster: str
    node: str
    storage: str
    type: str
    content: list[str]
    active: bool
    enabled: bool
    shared: bool
    total: int | None
    used: int | None
    avail: int | None


class VolumeRow(Row):
    """A volume on a storage."""

    volid: str
    content: str
    format: str | None
    size: int | None
    used: int | None
    vmid: int | None
    ctime: datetime | None
    protected: bool
    untrusted: NotesText


class StorageContentResult(ToolOutput):
    """Result of ``proxmox.storage.content``."""

    cluster: str
    node: str
    storage: str
    volumes: list[VolumeRow]


class DiskRow(Row):
    """A physical disk with health and what occupies it."""

    devpath: str
    by_id_link: str | None
    type: str | None
    size: int | None
    model: str | None
    serial: str | None
    vendor: str | None
    wwn: str | None
    health: str | None
    wearout: int | None = Field(description="Remaining endurance in percent, when known.")
    used: str | None = Field(description="What occupies the disk; null when PVE found nothing.")
    gpt: bool
    parent: str | None


class DiskListResult(ToolOutput):
    """Result of ``proxmox.disk.list``."""

    cluster: str
    node: str
    disks: list[DiskRow]


class SmartAttributeRow(Row):
    """One ATA SMART attribute."""

    id: int | str
    name: str
    value: int | str | None
    worst: int | str | None
    threshold: int | str | None
    raw: str | None
    fail: str | None


class SmartResult(ToolOutput):
    """Result of ``proxmox.disk.smart``."""

    cluster: str
    node: str
    disk: str
    health: str
    type: str | None
    attributes: list[SmartAttributeRow]
    untrusted: SmartText


class InterfaceRow(Row):
    """A network interface or bridge as staged."""

    iface: str
    type: str
    active: bool
    autostart: bool
    method: str | None
    method6: str | None
    address: str | None
    netmask: str | None
    cidr: str | None
    gateway: str | None
    bridge_ports: str | None
    families: list[str]
    untrusted: NotesText


class NetworkResult(ToolOutput):
    """Result of ``proxmox.network.list``."""

    cluster: str
    node: str
    interfaces: list[InterfaceRow]
    has_pending_changes: bool
    untrusted: NetworkText


class PoolMemberRow(Row):
    """A guest or storage in a pool."""

    id: str
    type: str
    node: str | None
    vmid: int | None
    storage: str | None


class PoolRow(Row):
    """A resource pool."""

    poolid: str
    members: list[PoolMemberRow]
    untrusted: NotesText


class PoolListResult(ToolOutput):
    """Result of ``proxmox.pool.list``."""

    cluster: str
    pools: list[PoolRow]


class TaskRow(Row):
    """A task from the task history."""

    upid: str
    node: str
    type: str
    user: str
    id: str | None
    starttime: datetime
    endtime: datetime | None
    outcome: TaskOutcomeName
    untrusted: TaskRowText


class TaskListResult(ToolOutput):
    """Result of ``proxmox.task.list``."""

    cluster: str
    tasks: list[TaskRow]


class TaskResult(ToolOutput):
    """Result of ``proxmox.task.get``."""

    cluster: str
    upid: str
    node: str
    type: str
    user: str
    id: str | None
    status: str
    outcome: TaskOutcomeName
    starttime: datetime | None
    log_total: int | None
    untrusted: TaskText


class HaRow(Row):
    """One row of the HA manager status: quorum, master, an LRM or a service."""

    id: str
    type: str
    node: str | None
    status: str | None
    quorate: bool | None
    sid: str | None
    state: str | None
    crm_state: str | None
    request_state: str | None


class HaStatusResult(ToolOutput):
    """Result of ``proxmox.ha.status``."""

    cluster: str
    entries: list[HaRow]


class BackupJobRow(Row):
    """A scheduled vzdump job."""

    id: str
    schedule: str | None
    enabled: bool
    storage: str | None
    node: str | None
    vmids: list[str]
    all: bool
    pool: str | None
    mode: str | None
    compress: str | None
    next_run: datetime | None
    untrusted: NotesText


class BackupJobsResult(ToolOutput):
    """Result of ``proxmox.backup.jobs``."""

    cluster: str
    jobs: list[BackupJobRow]


class RrdPointRow(Row):
    """One metrics sample; metrics PVE omitted for the interval are absent."""

    time: datetime
    cpu: float | None
    maxcpu: float | None
    memused: float | None
    memtotal: float | None
    loadavg: float | None
    other: dict[str, float] = Field(description="Remaining numeric series (netin, iowait, …).")


class RrdResult(ToolOutput):
    """Result of ``proxmox.metrics.rrd``."""

    cluster: str
    node: str
    timeframe: RrdTimeframe
    cf: RrdConsolidation
    points: list[RrdPointRow]
