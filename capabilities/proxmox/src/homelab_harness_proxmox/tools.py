"""Proxmox read tools (T0, §4.1): thin functions over the read-only adapter.

Each tool reads with the ``read`` credential tier, never writes (S1), and
returns a :mod:`~homelab_harness_proxmox.views` result: target-sourced text in
``untrusted`` envelopes (S7) and guest config masked (§9). Errors are the
adapter's ``homelab_harness_sdk.errors``; core turns them into MCP tool errors.

The docstrings are the tool descriptions the model sees.
"""

from __future__ import annotations

from typing import Any

from homelab_harness_proxmox import identifiers
from homelab_harness_proxmox.adapter import ProxmoxClient
from homelab_harness_proxmox.masking import mask_guest_config
from homelab_harness_proxmox.models import (
    Guest,
    GuestType,
    ResourceType,
    Task,
    TaskOutcome,
    Usage,
)
from homelab_harness_proxmox.views import (
    AllClustersArgs,
    BackupJobRow,
    BackupJobsResult,
    ClusterArgs,
    ClusterListResult,
    ClusterNodeRow,
    ClusterSummary,
    DiskListResult,
    DiskRow,
    DiskSmartArgs,
    GuestConfigText,
    GuestGetArgs,
    GuestListArgs,
    GuestListResult,
    GuestResult,
    GuestRow,
    GuestText,
    HaRow,
    HaStatusResult,
    InterfaceRow,
    NetworkResult,
    NetworkText,
    NodeArgs,
    NodeListResult,
    NodeResult,
    NodeRow,
    NotesText,
    PoolArgs,
    PoolListResult,
    PoolMemberRow,
    PoolRow,
    ResourceRow,
    ResourcesArgs,
    ResourcesResult,
    RrdArgs,
    RrdPointRow,
    RrdResult,
    SmartAttributeRow,
    SmartResult,
    SmartText,
    StorageArgs,
    StorageContentArgs,
    StorageContentResult,
    StorageListResult,
    StorageRow,
    StorageStatusResult,
    TaskGetArgs,
    TaskListArgs,
    TaskListResult,
    TaskOutcomeName,
    TaskResult,
    TaskRow,
    TaskRowText,
    TaskText,
    UsageView,
    VolumeRow,
)
from homelab_harness_sdk import HarnessError, NotFound, ReadTool, ToolContext, read_tool

type Ctx = ToolContext[ProxmoxClient]

READ = "read"


def _cluster(ctx: Ctx, name: str | None) -> str:
    """The cluster name a result reports: the given one, or the only registered one."""
    if name is not None:
        return name
    return ctx.targets[0] if len(ctx.targets) == 1 else ""


def _usage(value: Usage | None) -> UsageView | None:
    if value is None:
        return None
    return UsageView(total=value.total, used=value.used, free=value.free)


def _task_outcome(task: Task) -> TaskOutcomeName:
    # /tasks rows carry the exit text in "status" once the task has ended.
    if task.endtime is None:
        return "running"
    if task.status == "OK":
        return "ok"
    if task.status is not None and task.status.startswith("WARNINGS"):
        return "warnings"
    return "failed"


def _guest_row(guest: Guest) -> GuestRow:
    return GuestRow(
        vmid=guest.vmid,
        type=guest.type,
        node=guest.node,
        status=guest.status,
        lock=guest.lock,
        template=guest.template,
        cpus=guest.cpus,
        maxmem=guest.maxmem,
        maxdisk=guest.maxdisk,
        uptime=guest.uptime,
        untrusted=GuestText(name=guest.name, tags=guest.tags),
    )


# -- cluster -----------------------------------------------------------------------------


@read_tool(name="proxmox.cluster.list", credential=READ, title="List Proxmox clusters")
async def cluster_list(ctx: Ctx, args: AllClustersArgs) -> ClusterListResult:
    """List the registered Proxmox clusters with quorum, nodes and PVE version.

    A cluster that cannot be read is listed with reachable=false and an
    owner-safe error instead of failing the whole call.
    """
    names = [args.cluster] if args.cluster is not None else list(ctx.targets)
    summaries: list[ClusterSummary] = []
    for name in names:
        try:
            async with ctx.adapter(name) as pve:
                status = await pve.cluster_status()
                version = await pve.version()
        except HarnessError as exc:
            summaries.append(
                ClusterSummary(
                    cluster=name,
                    reachable=False,
                    error=exc.safe_message,
                    pve_cluster_name=None,
                    quorate=None,
                    version=None,
                    nodes=[],
                )
            )
            continue
        cluster_row = next((e for e in status.items if e.type == "cluster"), None)
        node_rows = [e for e in status.items if e.type == "node"]
        summaries.append(
            ClusterSummary(
                cluster=name,
                reachable=True,
                error=None,
                pve_cluster_name=cluster_row.name if cluster_row else None,
                # A standalone node has no cluster row and is trivially quorate.
                quorate=cluster_row.quorate if cluster_row else True,
                version=version.version,
                nodes=[
                    ClusterNodeRow(name=n.name, nodeid=n.nodeid, ip=n.ip, online=n.online)
                    for n in node_rows
                ],
            )
        )
    return ClusterListResult(as_of=ctx.now(), clusters=summaries)


@read_tool(name="proxmox.cluster.resources", credential=READ, title="Cluster resources")
async def cluster_resources(ctx: Ctx, args: ResourcesArgs) -> ResourcesResult:
    """List every guest, node, storage and SDN object of a cluster with usage.

    Filter by type (vm, storage, node, sdn), node, pool or guest tag. CPU is a
    fraction of maxcpu; memory and disk are bytes.
    """
    if args.node is not None:
        identifiers.node_name(args.node)
    async with ctx.adapter(args.cluster) as pve:
        listing = await pve.cluster_resources(
            ResourceType(args.type) if args.type is not None else None
        )
    rows = [
        r
        for r in listing.items
        if (args.node is None or r.node == args.node)
        and (args.pool is None or r.pool == args.pool)
        and (args.tag is None or args.tag in r.tags)
    ]
    return ResourcesResult(
        as_of=listing.as_of,
        cluster=_cluster(ctx, args.cluster),
        resources=[
            ResourceRow(
                id=r.id,
                type=r.type,
                node=r.node,
                status=r.status,
                vmid=r.vmid,
                pool=r.pool,
                template=r.template,
                lock=r.lock,
                hastate=r.hastate,
                storage=r.storage,
                cpu=r.cpu,
                maxcpu=r.maxcpu,
                mem=r.mem,
                maxmem=r.maxmem,
                disk=r.disk,
                maxdisk=r.maxdisk,
                uptime=r.uptime,
                untrusted=GuestText(name=r.name, tags=r.tags),
            )
            for r in rows
        ],
    )


@read_tool(name="proxmox.ha.status", credential=READ, title="HA status")
async def ha_status(ctx: Ctx, args: ClusterArgs) -> HaStatusResult:
    """Show the HA manager status: quorum, the master, each node's LRM and each HA service."""
    async with ctx.adapter(args.cluster) as pve:
        listing = await pve.ha_status()
    return HaStatusResult(
        as_of=listing.as_of,
        cluster=_cluster(ctx, args.cluster),
        entries=[
            HaRow(
                id=e.id,
                type=e.type,
                node=e.node,
                status=e.status,
                quorate=e.quorate,
                sid=e.sid,
                state=e.state,
                crm_state=e.crm_state,
                request_state=e.request_state,
            )
            for e in listing.items
        ],
    )


@read_tool(name="proxmox.backup.jobs", credential=READ, title="Backup jobs")
async def backup_jobs(ctx: Ctx, args: ClusterArgs) -> BackupJobsResult:
    """List scheduled backup (vzdump) jobs: schedule, target storage, guests and next run."""
    async with ctx.adapter(args.cluster) as pve:
        listing = await pve.backup_jobs()
    return BackupJobsResult(
        as_of=listing.as_of,
        cluster=_cluster(ctx, args.cluster),
        jobs=[
            BackupJobRow(
                id=j.id,
                schedule=j.schedule,
                enabled=j.enabled,
                storage=j.storage,
                node=j.node,
                vmids=j.vmid,
                all=j.all,
                pool=j.pool,
                mode=j.mode,
                compress=j.compress,
                next_run=j.next_run,
                untrusted=NotesText(notes=j.comment),
            )
            for j in listing.items
        ],
    )


@read_tool(name="proxmox.pool.list", credential=READ, title="Resource pools")
async def pool_list(ctx: Ctx, args: PoolArgs) -> PoolListResult:
    """List resource pools; with a pool ID, that pool with its guest and storage members."""
    async with ctx.adapter(args.cluster) as pve:
        listing = await pve.list_pools(args.pool)
    return PoolListResult(
        as_of=listing.as_of,
        cluster=_cluster(ctx, args.cluster),
        pools=[
            PoolRow(
                poolid=p.poolid,
                members=[
                    PoolMemberRow(id=m.id, type=m.type, node=m.node, vmid=m.vmid, storage=m.storage)
                    for m in p.members
                ],
                untrusted=NotesText(notes=p.comment),
            )
            for p in listing.items
        ],
    )


# -- nodes -------------------------------------------------------------------------------


@read_tool(name="proxmox.node.list", credential=READ, title="List nodes")
async def node_list(ctx: Ctx, args: ClusterArgs) -> NodeListResult:
    """List the cluster's nodes with online status, CPU, memory, disk and uptime."""
    async with ctx.adapter(args.cluster) as pve:
        listing = await pve.list_nodes()
    return NodeListResult(
        as_of=listing.as_of,
        cluster=_cluster(ctx, args.cluster),
        nodes=[
            NodeRow(
                node=n.node,
                status=n.status,
                cpu=n.cpu,
                maxcpu=n.maxcpu,
                mem=n.mem,
                maxmem=n.maxmem,
                disk=n.disk,
                maxdisk=n.maxdisk,
                uptime=n.uptime,
                ssl_fingerprint=n.ssl_fingerprint,
            )
            for n in listing.items
        ],
    )


@read_tool(name="proxmox.node.get", credential=READ, title="Node status")
async def node_get(ctx: Ctx, args: NodeArgs) -> NodeResult:
    """Show one node's CPU, memory, swap, root filesystem, load, kernel and PVE version."""
    async with ctx.adapter(args.cluster) as pve:
        status = await pve.node_status(args.node)
    cpu = status.cpuinfo
    return NodeResult(
        as_of=status.as_of,
        cluster=_cluster(ctx, args.cluster),
        node=args.node,
        uptime=status.uptime,
        cpu=status.cpu,
        cpu_model=cpu.model if cpu else None,
        cpus=cpu.cpus if cpu else None,
        sockets=cpu.sockets if cpu else None,
        memory=_usage(status.memory),
        swap=_usage(status.swap),
        rootfs=_usage(status.rootfs),
        loadavg=status.loadavg,
        kernel=status.kversion,
        pve_version=status.pveversion,
    )


@read_tool(name="proxmox.network.list", credential=READ, title="Node network")
async def network_list(ctx: Ctx, args: NodeArgs) -> NetworkResult:
    """List a node's interfaces and bridges, including staged changes not yet applied."""
    async with ctx.adapter(args.cluster) as pve:
        network = await pve.network(args.node)
    return NetworkResult(
        as_of=network.as_of,
        cluster=_cluster(ctx, args.cluster),
        node=args.node,
        interfaces=[
            InterfaceRow(
                iface=i.iface,
                type=i.type,
                active=i.active,
                autostart=i.autostart,
                method=i.method,
                method6=i.method6,
                address=i.address,
                netmask=i.netmask,
                cidr=i.cidr,
                gateway=i.gateway,
                bridge_ports=i.bridge_ports,
                families=i.families,
                untrusted=NotesText(notes=i.comments),
            )
            for i in network.interfaces
        ],
        has_pending_changes=network.pending_changes is not None,
        untrusted=NetworkText(pending_changes=network.pending_changes),
    )


@read_tool(name="proxmox.metrics.rrd", credential=READ, title="Node metrics")
async def metrics_rrd(ctx: Ctx, args: RrdArgs) -> RrdResult:
    """Read a node's metrics time series (CPU, memory, load, network, I/O) over a window."""
    async with ctx.adapter(args.cluster) as pve:
        listing = await pve.node_rrd(args.node, timeframe=args.timeframe, cf=args.cf)
    points: list[RrdPointRow] = []
    for p in listing.items:
        extra: dict[str, Any] = p.model_extra or {}
        other = {
            k: float(v)
            for k, v in extra.items()
            if isinstance(v, int | float) and not isinstance(v, bool)
        }
        points.append(
            RrdPointRow(
                time=p.time,
                cpu=p.cpu,
                maxcpu=p.maxcpu,
                memused=p.memused,
                memtotal=p.memtotal,
                loadavg=p.loadavg,
                other=other,
            )
        )
    return RrdResult(
        as_of=listing.as_of,
        cluster=_cluster(ctx, args.cluster),
        node=args.node,
        timeframe=args.timeframe,
        cf=args.cf,
        points=points,
    )


# -- guests ------------------------------------------------------------------------------


@read_tool(name="proxmox.guest.list", credential=READ, title="List guests")
async def guest_list(ctx: Ctx, args: GuestListArgs) -> GuestListResult:
    """List VMs (qemu) and containers (lxc) with status, lock, size and uptime.

    Without a node, every online node is read; nodes that fail are reported in
    unreachable_nodes rather than failing the call.
    """
    kinds: list[GuestType] = [args.type] if args.type is not None else ["qemu", "lxc"]
    guests: list[GuestRow] = []
    unreachable: list[str] = []
    async with ctx.adapter(args.cluster) as pve:
        if args.node is not None:
            nodes = [args.node]
        else:
            nodes = [n.node for n in (await pve.list_nodes()).items if n.status == "online"]
        as_of = ctx.now()
        for node in nodes:
            try:
                for kind in kinds:
                    guests.extend(_guest_row(g) for g in (await pve.list_guests(node, kind)).items)
            except HarnessError:
                if args.node is not None:
                    raise
                unreachable.append(node)
    return GuestListResult(
        as_of=as_of,
        cluster=_cluster(ctx, args.cluster),
        guests=sorted(guests, key=lambda g: g.vmid),
        unreachable_nodes=unreachable,
    )


@read_tool(name="proxmox.guest.get", credential=READ, title="Guest detail")
async def guest_get(ctx: Ctx, args: GuestGetArgs) -> GuestResult:
    """Show one guest: run state, lock, HA state, and its config with secrets masked.

    Secret-bearing config values (passwords, tokens, keys, cicustom, hookscript,
    args) are '[MASKED]'; SSH keys are shown only as fingerprints. The config
    digest is included for later plans.
    """
    async with ctx.adapter(args.cluster) as pve:
        node, kind = args.node, args.type
        if node is None or kind is None:
            match = next(
                (
                    r
                    for r in (await pve.cluster_resources(ResourceType.VM)).items
                    if r.vmid == args.vmid
                ),
                None,
            )
            if match is None or match.node is None or match.type not in ("qemu", "lxc"):
                raise NotFound(f"no guest with VMID {args.vmid} in this cluster")
            node = node or match.node
            kind = kind or ("qemu" if match.type == "qemu" else "lxc")
        status = await pve.guest_status(node, args.vmid, kind)
        config = await pve.guest_config(node, args.vmid, kind)
    masked = mask_guest_config(config.raw)
    ha_state = status.ha.get("state")
    return GuestResult(
        as_of=status.as_of,
        cluster=_cluster(ctx, args.cluster),
        vmid=args.vmid,
        type=kind,
        node=node,
        status=status.status,
        qmpstatus=status.qmpstatus,
        lock=config.lock or status.lock,
        template=config.template,
        uptime=status.uptime,
        cpu=status.cpu,
        mem=status.mem,
        maxmem=status.maxmem,
        ha_managed=bool(status.ha.get("managed", 0)),
        ha_state=ha_state if isinstance(ha_state, str) else None,
        digest=config.digest,
        masked_keys=masked.masked_keys,
        ssh_key_fingerprints=masked.ssh_key_fingerprints,
        untrusted=GuestConfigText(
            name=config.name,
            tags=config.tags,
            description=config.raw.get("description"),
            config=masked.values,
        ),
    )


# -- storage and disks -------------------------------------------------------------------


@read_tool(name="proxmox.storage.list", credential=READ, title="List storages")
async def storage_list(ctx: Ctx, args: ClusterArgs) -> StorageListResult:
    """List the datacenter's storage definitions: type, content types, shared, nodes."""
    async with ctx.adapter(args.cluster) as pve:
        listing = await pve.list_storage()
    return StorageListResult(
        as_of=listing.as_of,
        cluster=_cluster(ctx, args.cluster),
        storages=[
            StorageRow(
                storage=s.storage,
                type=s.type,
                content=s.content,
                shared=s.shared,
                disabled=s.disable,
                nodes=s.nodes,
            )
            for s in listing.items
        ],
    )


@read_tool(name="proxmox.storage.status", credential=READ, title="Storage usage")
async def storage_status(ctx: Ctx, args: StorageArgs) -> StorageStatusResult:
    """Show one storage's usage on one node: total, used and available bytes, active state."""
    async with ctx.adapter(args.cluster) as pve:
        status = await pve.storage_status(args.node, args.storage)
    return StorageStatusResult(
        as_of=status.as_of,
        cluster=_cluster(ctx, args.cluster),
        node=args.node,
        storage=args.storage,
        type=status.type,
        content=status.content,
        active=status.active,
        enabled=status.enabled,
        shared=status.shared,
        total=status.total,
        used=status.used,
        avail=status.avail,
    )


@read_tool(name="proxmox.storage.content", credential=READ, title="Storage content")
async def storage_content(ctx: Ctx, args: StorageContentArgs) -> StorageContentResult:
    """List the volumes on a storage (disk images, backups, ISOs, templates), optionally by type."""
    async with ctx.adapter(args.cluster) as pve:
        listing = await pve.storage_content(args.node, args.storage, content=args.content)
    return StorageContentResult(
        as_of=listing.as_of,
        cluster=_cluster(ctx, args.cluster),
        node=args.node,
        storage=args.storage,
        volumes=[
            VolumeRow(
                volid=v.volid,
                content=v.content,
                format=v.format,
                size=v.size,
                used=v.used,
                vmid=v.vmid,
                ctime=v.ctime,
                protected=v.protected,
                untrusted=NotesText(notes=v.notes),
            )
            for v in listing.items
        ],
    )


@read_tool(name="proxmox.disk.list", credential=READ, title="Physical disks")
async def disk_list(ctx: Ctx, args: NodeArgs) -> DiskListResult:
    """List a node's physical disks: path, by-id path, serial, model, size, health, wearout, use.

    A disk whose 'used' is null holds nothing PVE recognises (no partitions,
    LVM, ZFS, Ceph or mount): this answers "which disks are new and empty?".
    """
    async with ctx.adapter(args.cluster) as pve:
        listing = await pve.list_disks(args.node)
    return DiskListResult(
        as_of=listing.as_of,
        cluster=_cluster(ctx, args.cluster),
        node=args.node,
        disks=[
            DiskRow(
                devpath=d.devpath,
                by_id_link=d.by_id_link,
                type=d.type,
                size=d.size,
                model=d.model,
                serial=d.serial,
                vendor=d.vendor,
                wwn=d.wwn,
                health=d.health,
                wearout=d.wearout,
                used=d.used,
                gpt=d.gpt,
                parent=d.parent,
            )
            for d in listing.items
        ],
    )


@read_tool(name="proxmox.disk.smart", credential=READ, title="Disk SMART")
async def disk_smart(ctx: Ctx, args: DiskSmartArgs) -> SmartResult:
    """Show SMART health and attributes of one disk (NVMe and SAS disks report text)."""
    async with ctx.adapter(args.cluster) as pve:
        smart = await pve.disk_smart(args.node, args.disk)
    return SmartResult(
        as_of=ctx.now(),
        cluster=_cluster(ctx, args.cluster),
        node=args.node,
        disk=args.disk,
        health=smart.health,
        type=smart.type,
        attributes=[
            SmartAttributeRow(
                id=a.id,
                name=a.name,
                value=a.value,
                worst=a.worst,
                threshold=a.threshold,
                raw=a.raw,
                fail=a.fail,
            )
            for a in smart.attributes
        ],
        untrusted=SmartText(text=smart.text),
    )


# -- tasks -------------------------------------------------------------------------------


@read_tool(name="proxmox.task.list", credential=READ, title="Task history")
async def task_list(ctx: Ctx, args: TaskListArgs) -> TaskListResult:
    """List recent tasks (backups, starts, migrations …), newest first, with their outcome.

    With a node, that node's history is read and the filters apply on the
    server; without one, the cluster's recent-task list is filtered here.
    """
    async with ctx.adapter(args.cluster) as pve:
        if args.node is not None:
            listing = await pve.list_node_tasks(
                args.node, typefilter=args.type, vmid=args.vmid, limit=args.limit
            )
            tasks = listing.items
        else:
            listing = await pve.list_cluster_tasks()
            tasks = [
                t
                for t in listing.items
                if (args.type is None or t.type == args.type)
                and (args.vmid is None or t.id == str(args.vmid))
            ][: args.limit]
    return TaskListResult(
        as_of=listing.as_of,
        cluster=_cluster(ctx, args.cluster),
        tasks=[
            TaskRow(
                upid=t.upid,
                node=t.node,
                type=t.type,
                user=t.user,
                id=t.id,
                starttime=t.starttime,
                endtime=t.endtime,
                outcome=_task_outcome(t),
                untrusted=TaskRowText(status=t.status),
            )
            for t in tasks
        ],
    )


@read_tool(name="proxmox.task.get", credential=READ, title="Task detail")
async def task_get(ctx: Ctx, args: TaskGetArgs) -> TaskResult:
    """Show one task's status and outcome with a window of its log (default the first 50 lines)."""
    async with ctx.adapter(args.cluster) as pve:
        status = await pve.task_status(args.upid)
        as_of = ctx.now()
        log = (
            await pve.task_log(args.upid, start=args.log_start, limit=args.log_limit)
            if args.log_limit > 0
            else None
        )
    outcome: TaskOutcome = status.outcome
    return TaskResult(
        as_of=as_of,
        cluster=_cluster(ctx, args.cluster),
        upid=status.upid,
        node=status.node,
        type=status.type,
        user=status.user,
        id=status.id,
        status=status.status,
        outcome=outcome.value,
        starttime=status.starttime,
        log_total=log.total if log is not None else None,
        untrusted=TaskText(
            exitstatus=status.exitstatus,
            log=[line.t for line in log.lines] if log is not None else [],
        ),
    )


TOOLS: tuple[ReadTool[ProxmoxClient, Any, Any], ...] = (
    cluster_list,
    cluster_resources,
    node_list,
    node_get,
    guest_list,
    guest_get,
    storage_list,
    storage_status,
    storage_content,
    disk_list,
    disk_smart,
    network_list,
    pool_list,
    ha_status,
    backup_jobs,
    task_list,
    task_get,
    metrics_rrd,
)
"""Every Proxmox tool, in the order ``tools/list`` shows them."""
