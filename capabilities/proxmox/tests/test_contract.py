"""The shared contract kit, applied to the Proxmox capability."""

import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import ClassVar
from urllib.parse import quote

import httpx

from homelab_harness_proxmox import ApiToken, Endpoint, ProxmoxClient, SystemTrust
from homelab_harness_proxmox.capability import CAPABILITY
from homelab_harness_sdk.testing import CapabilityContract

FIXTURES = Path(__file__).parent / "fixtures" / "pve-9.2"
HOST = "pve1.lab.invalid"
API = "/api2/json"
UPID = "UPID:pve1:0001A2B3:00C4D5E6:6720F3A1:qmstart:101:harness@pve!guest-ops:"


def _load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def planted_qemu_config(canary):
    """The qemu config fixture with the canary in every field §9 says must not leave."""
    body = copy.deepcopy(_load("qemu-config/ok"))
    body["data"].update(
        {
            "cipassword": canary,
            "sshkeys": quote(
                f"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEXAMPLEEXAMPLEEXAMPLE0 {canary}"
            ),
            "args": f"-fw_cfg name=opt/x,string={canary}",
            "hookscript": f"local:snippets/{canary}.pl",
            "cicustom": f"user=local:snippets/{canary}.yml",
            "apitoken": canary,
            "secret_note": canary,
            "ipmi_key": canary,
        }
    )
    return body


class TestProxmoxContract(CapabilityContract):
    capability = CAPABILITY
    sample_arguments: ClassVar = {
        "proxmox.cluster.list": {},
        "proxmox.cluster.resources": {"type": "vm"},
        "proxmox.node.list": {},
        "proxmox.node.get": {"node": "pve1"},
        "proxmox.guest.list": {},
        "proxmox.guest.get": {"vmid": 101},
        "proxmox.storage.list": {},
        "proxmox.storage.status": {"node": "pve1", "storage": "local-zfs"},
        "proxmox.storage.content": {"node": "pve1", "storage": "pbs"},
        "proxmox.disk.list": {"node": "pve1"},
        "proxmox.disk.smart": {"node": "pve1", "disk": "/dev/sda"},
        "proxmox.network.list": {"node": "pve1"},
        "proxmox.pool.list": {},
        "proxmox.ha.status": {},
        "proxmox.backup.jobs": {},
        "proxmox.task.list": {"node": "pve1", "type": "qmstart"},
        "proxmox.task.get": {"upid": UPID},
        "proxmox.metrics.rrd": {"node": "pve1"},
    }
    # cluster.list reads every registered cluster and reports an unreachable one
    # in its result, so one bad cluster does not hide the others.
    tolerant_tools = frozenset({"proxmox.cluster.list"})
    trusted_text_fields: ClassVar = {
        "ClusterNodeRow.name": "a PVE node name: a validated identifier only root can set",
        "SmartAttributeRow.name": "a SMART attribute name from smartctl's fixed table",
    }

    def open_adapter(self, secret):
        @asynccontextmanager
        async def open_client():
            client = ProxmoxClient(
                endpoint=Endpoint(host=HOST),
                token=ApiToken(user="harness@pve", token_id="read", secret=secret),
                trust=SystemTrust(),
            )
            async with client:
                yield client

        return open_client()

    def install_routes(self, router, canary):
        def get(path, body):
            router.get(host=HOST, path=f"{API}{path}").mock(
                return_value=httpx.Response(200, json=body)
            )

        get("/version", _load("version/ok"))
        get("/cluster/status", _load("cluster-status/ok"))
        get("/cluster/resources", _load("cluster-resources/ok"))
        get("/cluster/ha/status/current", _load("ha-status/ok"))
        get("/cluster/backup", _load("cluster-backup/ok"))
        get("/cluster/tasks", _load("cluster-tasks/ok"))
        get("/pools", _load("pools/list"))
        get("/storage", _load("storage-list/ok"))
        get("/nodes", _load("nodes/ok"))
        get("/nodes/pve1/status", _load("node-status/ok"))
        get("/nodes/pve1/rrddata", _load("node-rrddata/ok"))
        get("/nodes/pve1/network", _load("network/pending"))
        get("/nodes/pve1/qemu", _load("qemu-list/ok"))
        get("/nodes/pve1/lxc", _load("lxc-list/ok"))
        get("/nodes/pve1/qemu/101/status/current", _load("qemu-status/ok"))
        get("/nodes/pve1/qemu/101/config", planted_qemu_config(canary))
        get("/nodes/pve1/storage/local-zfs/status", _load("storage-status/ok"))
        get("/nodes/pve1/storage/pbs/content", _load("storage-content/ok"))
        get("/nodes/pve1/disks/list", _load("disks-list/ok"))
        get("/nodes/pve1/disks/smart", _load("disks-smart/ata"))
        get("/nodes/pve1/tasks", _load("node-tasks/ok"))
        get(f"/nodes/pve1/tasks/{UPID}/status", _load("task-status/ok"))
        get(f"/nodes/pve1/tasks/{UPID}/log", _load("task-log/ok"))
