"""The UI façade's response models and how tool results map onto them (pure logic).

**Interim.** Until the Stage 2 lab state exists, the UI's tree and summaries
are built from Proxmox read-tool results. The façade reads each result as JSON
through the small ``_*`` models below (unknown fields ignored), so core depends
on the tools' published output schema, not on the capability package.

Object ids are stable strings the UI routes on:

- ``datacenter``: ``<cluster>``
- ``node``: ``<cluster>:<node>``
- ``qemu`` and ``lxc``: ``<cluster>:<vmid>``
- ``storage``: ``<cluster>:<node>:<storage>``

Target-sourced text (guest names, tags, config values) is passed through as
data and flagged ``untrusted`` where it appears in a summary (S7).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from homelab_harness_sdk.errors import InvalidInput

type ObjectType = Literal["datacenter", "node", "qemu", "lxc", "storage"]
type StatUnit = Literal["percent", "bytes", "seconds", "count"]

OBJECT_TYPES: tuple[ObjectType, ...] = ("datacenter", "node", "qemu", "lxc", "storage")

_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# -- responses ---------------------------------------------------------------------------


class TreeGuest(_Model):
    """A VM or container in the navigation tree."""

    id: str
    vmid: int
    type: Literal["qemu", "lxc"]
    name: str | None = Field(description="Target-sourced text (untrusted).")
    status: str | None
    template: bool


class TreeNode(_Model):
    """A node and the guests on it."""

    id: str
    name: str
    status: str | None
    guests: list[TreeGuest]


class TreeStorage(_Model):
    """One storage as seen from one node."""

    id: str
    storage: str
    node: str
    status: str | None


class TreeCluster(_Model):
    """A registered cluster (the UI's datacenter). Unreachable ones keep a safe error."""

    id: str
    name: str
    reachable: bool
    error: str | None
    as_of: datetime | None
    nodes: list[TreeNode]
    storages: list[TreeStorage]


class TreeResponse(_Model):
    """``GET /api/ui/tree``: every registered cluster with its nodes, guests and storages."""

    clusters: list[TreeCluster]


class SummaryStat(_Model):
    """A single number for a ``stat`` widget. ``max`` makes it a fraction of a whole."""

    key: str
    label: str
    value: float | None
    max: float | None = None
    unit: StatUnit


class SummaryProperty(_Model):
    """One labelled value for the properties table."""

    label: str
    value: str
    untrusted: bool = False


class SummaryChild(_Model):
    """An object listed on its parent's summary, for a ``status-list`` widget."""

    type: ObjectType
    id: str
    name: str
    status: str | None


class ObjectSummary(_Model):
    """``GET /api/ui/objects/{type}/{id}/summary``: what the Summary tab shows."""

    type: ObjectType
    id: str
    title: str
    status: str | None
    as_of: datetime
    stats: list[SummaryStat]
    properties: list[SummaryProperty]
    children: list[SummaryChild]


# -- object ids --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObjectRef:
    """A parsed object id.

    Attributes:
        type: The object type.
        cluster: The registered cluster name.
        node: The node, for nodes and storages.
        vmid: The guest id, for VMs and containers.
        storage: The storage id, for storages.
    """

    type: ObjectType
    cluster: str
    node: str | None = None
    vmid: int | None = None
    storage: str | None = None


def parse_object_id(object_type: ObjectType, object_id: str) -> ObjectRef:
    """Split an object id into its parts.

    Args:
        object_type: The object type from the route.
        object_id: The id from the route.

    Returns:
        The reference.

    Raises:
        InvalidInput: If the id does not have the shape its type needs.
    """
    parts = object_id.split(":")
    expected = {"datacenter": 1, "node": 2, "qemu": 2, "lxc": 2, "storage": 3}[object_type]
    if len(parts) != expected or not all(_PART.match(p) for p in parts):
        raise InvalidInput(f"malformed {object_type} id")
    match object_type:
        case "datacenter":
            return ObjectRef(type=object_type, cluster=parts[0])
        case "node":
            return ObjectRef(type=object_type, cluster=parts[0], node=parts[1])
        case "qemu" | "lxc":
            if not parts[1].isdigit():
                raise InvalidInput(f"malformed {object_type} id")
            return ObjectRef(type=object_type, cluster=parts[0], vmid=int(parts[1]))
        case "storage":
            return ObjectRef(type=object_type, cluster=parts[0], node=parts[1], storage=parts[2])


# -- tool results as read by the façade --------------------------------------------------


class _Read(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class _Text(_Read):
    name: str | None = None
    tags: list[str] = Field(default_factory=list[str])


class _Resource(_Read):
    type: str
    node: str | None = None
    status: str | None = None
    vmid: int | None = None
    template: bool = False
    storage: str | None = None
    untrusted: _Text = Field(default_factory=_Text)


class _Resources(_Read):
    as_of: datetime
    resources: list[_Resource]


class _ClusterNode(_Read):
    name: str
    online: bool | None = None


class _Cluster(_Read):
    cluster: str
    reachable: bool
    error: str | None = None
    pve_cluster_name: str | None = None
    quorate: bool | None = None
    version: str | None = None
    nodes: list[_ClusterNode] = Field(default_factory=list[_ClusterNode])


class _ClusterList(_Read):
    as_of: datetime
    clusters: list[_Cluster]


class _Usage(_Read):
    total: int | None = None
    used: int | None = None


class _Node(_Read):
    as_of: datetime
    node: str
    uptime: int | None = None
    cpu: float | None = None
    cpu_model: str | None = None
    cpus: int | None = None
    sockets: int | None = None
    memory: _Usage | None = None
    swap: _Usage | None = None
    rootfs: _Usage | None = None
    loadavg: list[str] = Field(default_factory=list[str])
    kernel: str | None = None
    pve_version: str | None = None


class _GuestText(_Read):
    name: str | None = None
    tags: list[str] = Field(default_factory=list[str])
    config: dict[str, Any] = Field(default_factory=dict[str, Any])


class _Guest(_Read):
    as_of: datetime
    vmid: int
    type: Literal["qemu", "lxc"]
    node: str
    status: str | None = None
    lock: str | None = None
    template: bool = False
    uptime: int | None = None
    cpu: float | None = None
    mem: int | None = None
    maxmem: int | None = None
    ha_managed: bool = False
    ha_state: str | None = None
    untrusted: _GuestText = Field(default_factory=_GuestText)


class _Storage(_Read):
    as_of: datetime
    node: str
    storage: str
    type: str
    content: list[str] = Field(default_factory=list[str])
    active: bool
    enabled: bool
    shared: bool
    total: int | None = None
    used: int | None = None


# -- mapping -----------------------------------------------------------------------------


def tree_cluster(cluster: str, resources: dict[str, Any]) -> TreeCluster:
    """Build one cluster's tree from a ``proxmox.cluster.resources`` result.

    A node that only appears as a guest's host (no ``node`` row) is still listed,
    with an unknown status, so no guest is hidden.

    Args:
        cluster: The registered cluster name.
        resources: The tool result as JSON.

    Returns:
        The cluster with nodes and storages in name order and guests by VMID.
    """
    listing = _Resources.model_validate(resources)
    statuses: dict[str, str | None] = {}
    guests: dict[str, list[TreeGuest]] = {}
    storages: list[TreeStorage] = []
    for row in listing.resources:
        if row.node is None:
            continue
        if row.type == "node":
            statuses[row.node] = row.status
        elif row.type in ("qemu", "lxc") and row.vmid is not None:
            guests.setdefault(row.node, []).append(
                TreeGuest(
                    id=f"{cluster}:{row.vmid}",
                    vmid=row.vmid,
                    type="qemu" if row.type == "qemu" else "lxc",
                    name=row.untrusted.name,
                    status=row.status,
                    template=row.template,
                )
            )
        elif row.type == "storage" and row.storage is not None:
            storages.append(
                TreeStorage(
                    id=f"{cluster}:{row.node}:{row.storage}",
                    storage=row.storage,
                    node=row.node,
                    status=row.status,
                )
            )
    nodes = [
        TreeNode(
            id=f"{cluster}:{name}",
            name=name,
            status=statuses.get(name),
            guests=sorted(guests.get(name, []), key=lambda g: g.vmid),
        )
        for name in sorted(statuses.keys() | guests.keys())
    ]
    return TreeCluster(
        id=cluster,
        name=cluster,
        reachable=True,
        error=None,
        as_of=listing.as_of,
        nodes=nodes,
        storages=sorted(storages, key=lambda s: (s.storage, s.node)),
    )


def unreachable_cluster(cluster: str, error: str) -> TreeCluster:
    """A cluster the façade could not read, with the owner-safe reason."""
    return TreeCluster(
        id=cluster, name=cluster, reachable=False, error=error, as_of=None, nodes=[], storages=[]
    )


def _flag(value: bool | None) -> str:
    return "unknown" if value is None else ("yes" if value else "no")


def _prop(label: str, value: object, *, untrusted: bool = False) -> SummaryProperty | None:
    if value is None or value == "" or value == []:
        return None
    text = str(value)
    if isinstance(value, list):
        text = ", ".join(str(v) for v in cast(list[object], value))
    return SummaryProperty(label=label, value=text, untrusted=untrusted)


def _props(*items: SummaryProperty | None) -> list[SummaryProperty]:
    return [p for p in items if p is not None]


def _used(key: str, label: str, usage: _Usage | None) -> SummaryStat:
    return SummaryStat(
        key=key,
        label=label,
        value=None if usage is None or usage.used is None else float(usage.used),
        max=None if usage is None or usage.total is None else float(usage.total),
        unit="bytes",
    )


def _percent(fraction: float | None) -> float | None:
    return None if fraction is None else round(fraction * 100, 1)


def _uptime(seconds: int | None) -> SummaryStat:
    return SummaryStat(
        key="uptime",
        label="Uptime",
        value=None if seconds is None else float(seconds),
        unit="seconds",
    )


def datacenter_summary(ref: ObjectRef, result: dict[str, Any]) -> ObjectSummary:
    """Summary of a datacenter from a ``proxmox.cluster.list`` result for one cluster.

    Raises:
        InvalidInput: If the result does not contain the cluster.
    """
    listing = _ClusterList.model_validate(result)
    found = next((c for c in listing.clusters if c.cluster == ref.cluster), None)
    if found is None:
        raise InvalidInput("the cluster is not in the result")
    online = sum(1 for n in found.nodes if n.online)
    return ObjectSummary(
        type="datacenter",
        id=ref.cluster,
        title=ref.cluster,
        status=("quorate" if found.quorate else "no quorum") if found.reachable else "unreachable",
        as_of=listing.as_of,
        stats=[
            SummaryStat(
                key="nodes_online",
                label="Nodes online",
                value=float(online),
                max=float(len(found.nodes)),
                unit="count",
            )
        ],
        properties=_props(
            _prop("Reachable", _flag(found.reachable)),
            _prop("Error", found.error),
            _prop("PVE cluster name", found.pve_cluster_name, untrusted=True),
            _prop("Quorate", _flag(found.quorate)),
            _prop("PVE version", found.version),
        ),
        children=[
            SummaryChild(
                type="node",
                id=f"{ref.cluster}:{n.name}",
                name=n.name,
                status=None if n.online is None else ("online" if n.online else "offline"),
            )
            for n in sorted(found.nodes, key=lambda n: n.name)
        ],
    )


def node_summary(ref: ObjectRef, result: dict[str, Any]) -> ObjectSummary:
    """Summary of a node from a ``proxmox.node.get`` result."""
    node = _Node.model_validate(result)
    return ObjectSummary(
        type="node",
        id=f"{ref.cluster}:{node.node}",
        title=node.node,
        status=None,
        as_of=node.as_of,
        stats=[
            SummaryStat(key="cpu", label="CPU", value=_percent(node.cpu), max=100, unit="percent"),
            _used("memory", "Memory", node.memory),
            _used("rootfs", "Root disk", node.rootfs),
            _uptime(node.uptime),
        ],
        properties=_props(
            _prop("CPU model", node.cpu_model),
            _prop("CPUs", node.cpus),
            _prop("Sockets", node.sockets),
            _prop("Load average", node.loadavg),
            _prop("Kernel", node.kernel),
            _prop("PVE version", node.pve_version),
        ),
        children=[],
    )


def guest_summary(ref: ObjectRef, result: dict[str, Any]) -> ObjectSummary:
    """Summary of a VM or container from a ``proxmox.guest.get`` result (config masked).

    Raises:
        InvalidInput: If the guest's type differs from the requested one.
    """
    guest = _Guest.model_validate(result)
    if guest.type != ref.type:
        raise InvalidInput(f"guest {guest.vmid} is a {guest.type}, not a {ref.type}")
    text = guest.untrusted
    config = [
        _prop(f"config: {key}", value, untrusted=True) for key, value in sorted(text.config.items())
    ]
    return ObjectSummary(
        type=guest.type,
        id=f"{ref.cluster}:{guest.vmid}",
        title=f"{guest.vmid} ({text.name})" if text.name else str(guest.vmid),
        status=guest.status,
        as_of=guest.as_of,
        stats=[
            SummaryStat(key="cpu", label="CPU", value=_percent(guest.cpu), max=100, unit="percent"),
            SummaryStat(
                key="memory",
                label="Memory",
                value=None if guest.mem is None else float(guest.mem),
                max=None if guest.maxmem is None else float(guest.maxmem),
                unit="bytes",
            ),
            _uptime(guest.uptime),
        ],
        properties=_props(
            _prop("Name", text.name, untrusted=True),
            _prop("Node", guest.node),
            _prop("Status", guest.status),
            _prop("Lock", guest.lock),
            _prop("Template", _flag(guest.template)),
            _prop("HA", guest.ha_state if guest.ha_managed else "not managed"),
            _prop("Tags", text.tags, untrusted=True),
            *config,
        ),
        children=[],
    )


def storage_summary(ref: ObjectRef, result: dict[str, Any]) -> ObjectSummary:
    """Summary of a storage on one node from a ``proxmox.storage.status`` result."""
    storage = _Storage.model_validate(result)
    return ObjectSummary(
        type="storage",
        id=f"{ref.cluster}:{storage.node}:{storage.storage}",
        title=f"{storage.storage} ({storage.node})",
        status="active" if storage.active else "inactive",
        as_of=storage.as_of,
        stats=[_used("usage", "Usage", _Usage(total=storage.total, used=storage.used))],
        properties=_props(
            _prop("Type", storage.type),
            _prop("Content", storage.content),
            _prop("Enabled", _flag(storage.enabled)),
            _prop("Shared", _flag(storage.shared)),
        ),
        children=[],
    )
