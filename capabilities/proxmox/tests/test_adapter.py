"""Every read method against respx-mocked responses built from the hand-written fixtures."""

from datetime import UTC, datetime
from urllib.parse import quote

import httpx
import pytest

from homelab_harness_proxmox import ApiToken, Endpoint, ProxmoxClient, SystemTrust, parse_upid
from homelab_harness_proxmox.models import (
    ResourceType,
    RrdConsolidation,
    RrdTimeframe,
    TaskOutcome,
)
from homelab_harness_sdk.errors import InvalidInput

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
UPID_START = "UPID:pve1:0001A2B3:00C4D5E6:6720F3A1:qmstart:101:harness@pve!guest-ops:"
UPID_BACKUP = "UPID:pve2:0002B3C4:00D5E6F7:6720F000:vzdump::root@pam:"


def _route(pve_mock, path, body, **params):
    return pve_mock.get(path, params=params or None).mock(
        return_value=httpx.Response(200, json=body)
    )


async def test_version(pve, pve_mock, load):
    _route(pve_mock, "/version", load("version/ok"))
    version = await pve.version()
    assert (version.version, version.release, version.repoid) == ("9.2.1", "9.2", "a1b2c3d4")


async def test_requests_carry_the_token_header(pve, pve_mock, load, canary_secret):
    route = _route(pve_mock, "/version", load("version/ok"))
    await pve.version()
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == f"PVEAPIToken=harness@pve!read={canary_secret}"
    assert sent.url.host == "pve1.lab.invalid"
    assert sent.url.port == 8006


async def test_cluster_status(pve, pve_mock, load):
    _route(pve_mock, "/cluster/status", load("cluster-status/ok"))
    status = await pve.cluster_status()
    cluster, pve1, pve2 = status.items
    assert (cluster.type, cluster.name, cluster.quorate, cluster.nodes) == (
        "cluster",
        "home",
        True,
        2,
    )
    assert (pve1.online, pve1.local, pve2.online) == (True, True, False)
    assert status.as_of == NOW


async def test_cluster_resources_normalises_tags_and_keeps_unknown_fields(pve, pve_mock, load):
    _route(pve_mock, "/cluster/resources", load("cluster-resources/ok"))
    resources = (await pve.cluster_resources()).items
    web = resources[0]
    assert web.tags == ["harness", "harness-plan-7f3c"]
    assert (web.pool, web.hastate, web.template) == ("agent-managed", "started", False)
    assert web.model_extra == {"netin": 1234, "netout": 5678, "diskread": 0, "diskwrite": 0}
    assert resources[1].lock == "backup"
    assert resources[2].template is True
    assert resources[4].storage == "local-zfs"


async def test_cluster_resources_type_filter(pve, pve_mock, load):
    route = _route(pve_mock, "/cluster/resources", load("cluster-resources/ok"), type="vm")
    await pve.cluster_resources(ResourceType.VM)
    assert route.called


async def test_list_nodes(pve, pve_mock, load):
    _route(pve_mock, "/nodes", load("nodes/ok"))
    nodes = (await pve.list_nodes()).items
    assert [(n.node, n.status) for n in nodes] == [("pve1", "online"), ("pve2", "offline")]
    assert nodes[0].maxcpu == 16
    assert nodes[1].mem is None


async def test_node_status(pve, pve_mock, load):
    _route(pve_mock, "/nodes/pve1/status", load("node-status/ok"))
    status = await pve.node_status("pve1")
    assert status.pveversion == "pve-manager/9.2.1/a1b2c3d4"
    assert status.cpuinfo is not None
    assert status.cpuinfo.cores == 16
    assert status.memory is not None
    assert status.memory.total == 68719476736
    assert status.loadavg == ["0.42", "0.38", "0.35"]
    assert status.as_of == NOW
    assert "boot-info" in (status.model_extra or {})


async def test_node_rrd(pve, pve_mock, load):
    route = _route(
        pve_mock, "/nodes/pve1/rrddata", load("node-rrddata/ok"), timeframe="day", cf="MAX"
    )
    points = (await pve.node_rrd("pve1", timeframe=RrdTimeframe.DAY, cf=RrdConsolidation.MAX)).items
    assert route.called
    assert points[0].time == datetime(2024, 10, 29, 14, 40, tzinfo=UTC)
    assert points[0].cpu == pytest.approx(0.081)
    assert (points[0].model_extra or {})["iowait"] == pytest.approx(0.001)
    assert points[1].cpu is None  # an interval with no data


@pytest.mark.parametrize(
    ("kind", "fixture_name"), [("qemu", "qemu-list/ok"), ("lxc", "lxc-list/ok")]
)
async def test_list_guests(pve, pve_mock, load, kind, fixture_name):
    _route(pve_mock, f"/nodes/pve1/{kind}", load(fixture_name))
    guests = (await pve.list_guests("pve1", kind)).items
    assert all(g.type == kind and g.node == "pve1" for g in guests)
    if kind == "qemu":
        assert guests[0].tags == ["harness", "web"]
        assert guests[1].template is True
    else:
        assert guests[0].vmid == 200  # PVE sends LXC vmids as strings
        assert guests[0].lock == "backup"


async def test_qemu_config_keeps_raw_and_digest(pve, pve_mock, load):
    _route(pve_mock, "/nodes/pve1/qemu/101/config", load("qemu-config/ok"))
    config = await pve.guest_config("pve1", 101, "qemu")
    assert config.digest == "3f7c2a9b1d4e5f60718293a4b5c6d7e8f9012345"
    assert (config.name, config.tags, config.lock, config.template) == (
        "web-01",
        ["harness", "harness-plan-7f3c"],
        None,
        False,
    )
    assert config.raw["net0"] == "virtio=BC:24:11:00:00:01,bridge=vmbr0"


async def test_lxc_config_uses_hostname(pve, pve_mock, load):
    _route(pve_mock, "/nodes/pve2/lxc/200/config", load("lxc-config/ok"))
    config = await pve.guest_config("pve2", 200, "lxc")
    assert (config.name, config.lock, config.type, config.node) == ("dns", "backup", "lxc", "pve2")


@pytest.mark.parametrize(
    ("kind", "vmid", "fixture_name", "status"),
    [("qemu", 101, "qemu-status/ok", "running"), ("lxc", 200, "lxc-status/ok", "stopped")],
)
async def test_guest_status(pve, pve_mock, load, kind, vmid, fixture_name, status):
    _route(pve_mock, f"/nodes/pve1/{kind}/{vmid}/status/current", load(fixture_name))
    current = await pve.guest_status("pve1", vmid, kind)
    assert current.status == status
    assert current.as_of == NOW
    if kind == "qemu":
        assert current.ha["managed"] == 1
        assert current.qmpstatus == "running"


async def test_list_storage(pve, pve_mock, load):
    _route(pve_mock, "/storage", load("storage-list/ok"))
    storages = (await pve.list_storage()).items
    assert storages[0].content == ["iso", "vztmpl", "backup"]
    assert storages[2].nodes == ["pve1", "pve2"]
    assert storages[2].shared is True
    assert storages[0].nodes is None


async def test_storage_status(pve, pve_mock, load):
    _route(pve_mock, "/nodes/pve1/storage/local-zfs/status", load("storage-status/ok"))
    status = await pve.storage_status("pve1", "local-zfs")
    assert (status.active, status.enabled, status.content) == (True, True, ["images", "rootdir"])
    assert status.avail == 946517794816


async def test_storage_content(pve, pve_mock, load):
    route = _route(
        pve_mock, "/nodes/pve1/storage/pbs/content", load("storage-content/ok"), content="backup"
    )
    volumes = (await pve.storage_content("pve1", "pbs", content="backup")).items
    assert route.called
    assert volumes[0].ctime == datetime(2024, 10, 31, 2, 0, tzinfo=UTC)
    assert volumes[1].protected is True
    assert volumes[0].model_extra == {"verification": {"state": "ok"}}


async def test_list_disks_uses_the_slow_read_timeout(pve, pve_mock, load):
    route = _route(
        pve_mock, "/nodes/pve1/disks/list", load("disks-list/ok"), **{"include-partitions": "1"}
    )
    disks = (await pve.list_disks("pve1")).items
    assert route.calls.last.request.extensions["timeout"]["read"] == 120.0
    nvme, ssd, hdd, part = disks
    assert (nvme.used, nvme.wearout, nvme.gpt) == ("ZFS", 98, True)
    assert ssd.used is None  # nothing on it: a candidate for a new pool
    assert ssd.by_id_link == "/dev/disk/by-id/ata-SAMSUNG_MZ7L31T9HBLT-00A07_S6ESNX0W123456"
    assert hdd.wearout is None  # "N/A"
    assert part.parent == "/dev/sdb"


async def test_disk_smart_ata_and_nvme(pve, pve_mock, load):
    pve_mock.get("/nodes/pve1/disks/smart", params={"disk": "/dev/sda"}).mock(
        return_value=httpx.Response(200, json=load("disks-smart/ata"))
    )
    pve_mock.get("/nodes/pve1/disks/smart", params={"disk": "/dev/nvme0n1"}).mock(
        return_value=httpx.Response(200, json=load("disks-smart/nvme"))
    )
    ata = await pve.disk_smart("pve1", "/dev/sda")
    assert ata.health == "PASSED"
    assert [a.name for a in ata.attributes] == ["Reallocated_Sector_Ct", "Wear_Leveling_Count"]
    nvme = await pve.disk_smart("pve1", "/dev/nvme0n1")
    assert nvme.attributes == []
    assert nvme.text is not None
    assert "Percentage Used" in nvme.text


async def test_network_without_and_with_pending_changes(pve, pve_mock, load):
    route = pve_mock.get("/nodes/pve1/network")
    route.side_effect = [
        httpx.Response(200, json=load("network/ok")),
        httpx.Response(200, json=load("network/pending")),
    ]
    applied = await pve.network("pve1")
    assert applied.pending_changes is None
    assert applied.interfaces[0].cidr == "192.0.2.11/24"
    assert applied.interfaces[0].families == ["inet"]
    pending = await pve.network("pve1")
    assert pending.pending_changes is not None
    assert pending.pending_changes.startswith("--- /etc/network/interfaces")


async def test_pools(pve, pve_mock, load):
    # The filtered route goes first: respx picks the first route that matches.
    route = _route(pve_mock, "/pools", load("pools/members"), poolid="agent-managed")
    _route(pve_mock, "/pools", load("pools/list"))
    assert [p.poolid for p in (await pve.list_pools()).items] == ["agent-managed", "lab"]
    pool = (await pve.list_pools("agent-managed")).items[0]
    assert route.called
    assert [m.id for m in pool.members] == ["qemu/101", "storage/pve1/local-zfs"]


async def test_cluster_tasks(pve, pve_mock, load):
    _route(pve_mock, "/cluster/tasks", load("cluster-tasks/ok"))
    tasks = (await pve.list_cluster_tasks()).items
    assert tasks[0].parsed_upid.node == "pve1"
    assert tasks[0].endtime == datetime(2024, 10, 29, 14, 39, 31, tzinfo=UTC)
    assert tasks[1].endtime is None


async def test_node_tasks_filters(pve, pve_mock, load):
    route = _route(
        pve_mock,
        "/nodes/pve2/tasks",
        load("node-tasks/ok"),
        start="0",
        limit="20",
        typefilter="vzdump",
        vmid="101",
    )
    tasks = (await pve.list_node_tasks("pve2", typefilter="vzdump", vmid=101, limit=20)).items
    assert route.called
    assert tasks[0].status == "WARNINGS: 1"


@pytest.mark.parametrize(
    ("case", "outcome"),
    [
        ("running", TaskOutcome.RUNNING),
        ("ok", TaskOutcome.OK),
        ("warnings", TaskOutcome.WARNINGS),
        ("failed", TaskOutcome.FAILED),
    ],
)
async def test_task_status_routes_to_the_upid_node(pve, pve_mock, load, case, outcome):
    body = load(f"task-status/{case}")
    upid = body["data"]["upid"]
    node = parse_upid(upid).node
    route = pve_mock.get(f"/nodes/{node}/tasks/{quote(upid, safe='')}/status").mock(
        return_value=httpx.Response(200, json=body)
    )
    status = await pve.task_status(upid)
    assert status.outcome is outcome
    # The UPID is a single, fully escaped path segment.
    assert route.calls.last.request.url.raw_path.decode().startswith(
        f"/api2/json/nodes/{node}/tasks/UPID%3A{node}%3A"
    )


async def test_task_log_window(pve, pve_mock, load):
    route = pve_mock.get(
        f"/nodes/pve1/tasks/{quote(UPID_START, safe='')}/log", params={"start": "2", "limit": "50"}
    ).mock(return_value=httpx.Response(200, json=load("task-log/ok")))
    log = await pve.task_log(parse_upid(UPID_START), start=2, limit=50)
    assert route.called
    assert [line.t for line in log.lines] == ["generating cloud-init ISO", "TASK OK"]
    assert log.total == 2


async def test_ha_status(pve, pve_mock, load):
    _route(pve_mock, "/cluster/ha/status/current", load("ha-status/ok"))
    entries = (await pve.ha_status()).items
    assert entries[0].quorate is True
    service = entries[-1]
    assert (service.sid, service.state, service.crm_state) == ("vm:101", "started", "started")


async def test_backup_jobs(pve, pve_mock, load):
    _route(pve_mock, "/cluster/backup", load("cluster-backup/ok"))
    nightly, weekly = (await pve.backup_jobs()).items
    assert nightly.vmid == ["101", "200"]
    assert nightly.next_run == datetime(2024, 11, 2, 2, 0, tzinfo=UTC)
    assert (nightly.model_extra or {})["prune-backups"] == {"keep-daily": "7"}
    assert (weekly.enabled, weekly.all, weekly.vmid) == (False, True, [])


# -- input validation at the boundary (R-18) ---------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda pve: pve.node_status("../cluster"),
        lambda pve: pve.node_status("pve1/qemu"),
        lambda pve: pve.guest_config("pve1", 99, "qemu"),
        lambda pve: pve.guest_config("pve1", 101, "openvz"),
        lambda pve: pve.guest_status("pve1", True, "qemu"),
        lambda pve: pve.storage_status("pve1", "../../access"),
        lambda pve: pve.storage_content("pve1", "pbs", content="images&x=1"),
        lambda pve: pve.disk_smart("pve1", "/dev/../etc/shadow"),
        lambda pve: pve.disk_smart("pve1", "sda"),
        lambda pve: pve.list_pools("a/b"),
        lambda pve: pve.list_node_tasks("pve1", typefilter="vz dump"),
        lambda pve: pve.list_node_tasks("pve1", limit=0),
        lambda pve: pve.task_status("not-a-upid"),
        lambda pve: pve.task_log(UPID_BACKUP, start=-1),
    ],
)
async def test_invalid_input_is_rejected_before_any_request(pve, pve_mock, call):
    with pytest.raises(InvalidInput):
        await call(pve)
    assert not pve_mock.calls


@pytest.mark.parametrize("host", ["", "pve1:8006", "user@pve1", "pve1/x", "pve 1"])
def test_endpoint_rejects_non_hosts(host):
    with pytest.raises(InvalidInput):
        Endpoint(host=host)


def test_endpoint_brackets_ipv6():
    assert Endpoint(host="fd00::11").base_url == "https://[fd00::11]:8006/api2/json"


async def test_client_must_be_entered(token: ApiToken):
    client = ProxmoxClient(endpoint=Endpoint(host="pve1"), token=token, trust=SystemTrust())
    with pytest.raises(RuntimeError, match="async with"):
        await client.version()
