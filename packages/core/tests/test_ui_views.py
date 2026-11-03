"""Mapping read-tool results onto the UI façade's tree and summaries (pure logic)."""

import pytest

from homelab_harness.ui.views import (
    ObjectRef,
    datacenter_summary,
    guest_summary,
    node_summary,
    parse_object_id,
    storage_summary,
    tree_cluster,
    unreachable_cluster,
)
from homelab_harness_sdk.errors import InvalidInput

AS_OF = "2026-11-01T12:00:00Z"


def resource(type_, node, **extra):
    return {"type": type_, "node": node, "untrusted": {"name": None, "tags": []}, **extra}


@pytest.mark.parametrize(
    ("object_type", "object_id", "expected"),
    [
        ("datacenter", "home", ObjectRef(type="datacenter", cluster="home")),
        ("node", "home:pve1", ObjectRef(type="node", cluster="home", node="pve1")),
        ("qemu", "home:101", ObjectRef(type="qemu", cluster="home", vmid=101)),
        ("lxc", "home:200", ObjectRef(type="lxc", cluster="home", vmid=200)),
        (
            "storage",
            "home:pve1:local-zfs",
            ObjectRef(type="storage", cluster="home", node="pve1", storage="local-zfs"),
        ),
    ],
)
def test_object_ids_parse(object_type, object_id, expected):
    assert parse_object_id(object_type, object_id) == expected


@pytest.mark.parametrize(
    ("object_type", "object_id"),
    [
        ("datacenter", "home:pve1"),
        ("node", "home"),
        ("qemu", "home:web"),
        ("storage", "home:pve1"),
        ("node", "home:../etc"),
        ("node", "home:"),
    ],
)
def test_malformed_object_ids_are_rejected(object_type, object_id):
    with pytest.raises(InvalidInput, match="malformed"):
        parse_object_id(object_type, object_id)


def test_tree_groups_guests_under_nodes_and_keeps_hostless_nodes():
    result = {
        "as_of": AS_OF,
        "cluster": "home",
        "resources": [
            resource("node", "pve1", status="online"),
            resource("qemu", "pve1", vmid=9000, status="stopped", template=True),
            resource(
                "qemu",
                "pve1",
                vmid=101,
                status="running",
                untrusted={"name": "web-01", "tags": []},
            ),
            resource("lxc", "pve2", vmid=200, status="stopped"),
            resource("storage", "pve1", storage="local-zfs", status="available"),
            resource("sdn", None),
        ],
    }
    cluster = tree_cluster("home", result)
    assert cluster.reachable is True
    assert [n.name for n in cluster.nodes] == ["pve1", "pve2"]
    pve1, pve2 = cluster.nodes
    assert pve1.id == "home:pve1"
    assert pve1.status == "online"
    assert [g.vmid for g in pve1.guests] == [101, 9000]
    assert pve1.guests[0].name == "web-01"
    assert pve1.guests[1].template is True
    # pve2 has no node row (it is offline), but its guest must still show.
    assert pve2.status is None
    assert [(g.id, g.type) for g in pve2.guests] == [("home:200", "lxc")]
    assert [s.id for s in cluster.storages] == ["home:pve1:local-zfs"]


def test_unreachable_cluster_keeps_its_error():
    cluster = unreachable_cluster("lab", "the cluster did not answer")
    assert cluster.reachable is False
    assert cluster.error == "the cluster did not answer"
    assert cluster.nodes == []


def test_datacenter_summary_counts_online_nodes():
    result = {
        "as_of": AS_OF,
        "clusters": [
            {
                "cluster": "home",
                "reachable": True,
                "error": None,
                "pve_cluster_name": "home",
                "quorate": True,
                "version": "9.2.1",
                "nodes": [{"name": "pve2", "online": False}, {"name": "pve1", "online": True}],
            }
        ],
    }
    summary = datacenter_summary(ObjectRef(type="datacenter", cluster="home"), result)
    assert summary.status == "quorate"
    (stat,) = summary.stats
    assert (stat.value, stat.max, stat.unit) == (1, 2, "count")
    assert [(c.id, c.status) for c in summary.children] == [
        ("home:pve1", "online"),
        ("home:pve2", "offline"),
    ]
    assert {p.label: p.value for p in summary.properties}["PVE version"] == "9.2.1"


def test_datacenter_summary_needs_the_cluster_in_the_result():
    with pytest.raises(InvalidInput):
        datacenter_summary(
            ObjectRef(type="datacenter", cluster="home"), {"as_of": AS_OF, "clusters": []}
        )


def test_node_summary_turns_fractions_into_percent_and_keeps_bytes():
    result = {
        "as_of": AS_OF,
        "cluster": "home",
        "node": "pve1",
        "uptime": 3600,
        "cpu": 0.08,
        "cpu_model": "AMD Ryzen 9",
        "cpus": 32,
        "sockets": 1,
        "memory": {"total": 100, "used": 25, "free": 75},
        "swap": None,
        "rootfs": None,
        "loadavg": ["0.42", "0.38", "0.35"],
        "kernel": "Linux 7.0",
        "pve_version": "pve-manager/9.2.1",
    }
    summary = node_summary(ObjectRef(type="node", cluster="home", node="pve1"), result)
    stats = {s.key: s for s in summary.stats}
    assert stats["cpu"].value == 8.0
    assert stats["cpu"].unit == "percent"
    assert (stats["memory"].value, stats["memory"].max) == (25, 100)
    assert stats["rootfs"].value is None
    assert stats["uptime"].value == 3600
    assert {p.label: p.value for p in summary.properties}["Load average"] == "0.42, 0.38, 0.35"


def guest(**overrides):
    return {
        "as_of": AS_OF,
        "cluster": "home",
        "vmid": 101,
        "type": "qemu",
        "node": "pve1",
        "status": "running",
        "lock": None,
        "template": False,
        "uptime": 60,
        "cpu": 0.5,
        "mem": 1,
        "maxmem": 4,
        "ha_managed": False,
        "ha_state": None,
        "untrusted": {
            "name": "web-01",
            "tags": ["prod"],
            "description": None,
            "config": {"cores": 2, "cipassword": "[MASKED]"},
        },
        **overrides,
    }


def test_guest_summary_flags_target_text_as_untrusted():
    summary = guest_summary(ObjectRef(type="qemu", cluster="home", vmid=101), guest())
    assert summary.title == "101 (web-01)"
    props = {p.label: p for p in summary.properties}
    assert props["Name"].untrusted is True
    assert props["Tags"].value == "prod"
    assert props["config: cipassword"].value == "[MASKED]"
    assert props["config: cipassword"].untrusted is True
    assert props["Node"].untrusted is False
    assert props["HA"].value == "not managed"


def test_guest_summary_rejects_a_type_mismatch():
    with pytest.raises(InvalidInput, match="is a qemu"):
        guest_summary(ObjectRef(type="lxc", cluster="home", vmid=101), guest())


def test_storage_summary_reports_usage_against_total():
    result = {
        "as_of": AS_OF,
        "cluster": "home",
        "node": "pve1",
        "storage": "local-zfs",
        "type": "zfspool",
        "content": ["images", "rootdir"],
        "active": True,
        "enabled": True,
        "shared": False,
        "total": 1000,
        "used": 50,
        "avail": 950,
    }
    ref = ObjectRef(type="storage", cluster="home", node="pve1", storage="local-zfs")
    summary = storage_summary(ref, result)
    (usage,) = summary.stats
    assert (usage.value, usage.max) == (50, 1000)
    assert summary.status == "active"
    assert {p.label: p.value for p in summary.properties}["Content"] == "images, rootdir"
