# Capability: Proxmox VE

> **Status: specification, partly implemented.** [roadmap.md](../../roadmap.md) says what gets built when.
>
> **Implemented** in `capabilities/proxmox` (package `homelab_harness_proxmox`), **mocked; not yet verified live**:
> - the read-only adapter (§3): the endpoints listed under "Adapter coverage" in §4.1, TLS trust per §2.1, the error mapping, and the UPID parser;
> - the bootstrap renderer (§2.4) as a pure function, `render_bootstrap_script()`. The `hh proxmox bootstrap` CLI command, `hh proxmox verify`, and the token vault are not built yet.
> - the read tools (§4.1) marked *implemented* in the table, served over MCP. Every tool carries `readOnlyHint`, `idempotentHint` and `openWorldHint: false`, and returns `as_of`. Target-sourced text sits in `untrusted` envelopes, and guest config is masked per §9. The shared contract kit runs against the capability (`tests/test_contract.py`).
> - **Interim targets:** clusters are registered in the `HH_TARGETS_FILE` TOML (name, `endpoints`, `tls`, and per tier a `token_id` with a `token_secret_file`), not through `hh proxmox register` and the vault. See [development.md](../../development.md#mcp-server). Reads use the cluster's first endpoint. Each cluster gets a `proxmox:<name>` readiness check, which reports `degraded` when unreachable.
>
> **Not yet built:** MCP resources and prompts (§8), inventory, plan tools, executors, events, retries at the adapter, node routing, and the minimum-version check at registration.

This is the primary capability: the reason the harness exists. It turns the Proxmox VE API into typed read tools, plan tools, and durable executors. Everything follows the [safety model](../safety-model.md): read, then plan, then approve, then apply, then verify. Vocabulary follows the [glossary](../../../GLOSSARY.md).

Facts marked **(unverified)** came from secondary sources or memory. Check them against a live PVE 9.2 node before implementing, and record the result in `docs/verification.md`.

---

## 1. Scope

| In v1 | Later | Out of scope |
|---|---|---|
| Proxmox VE **9.2+**: one or more clusters, standalone nodes count as one-node clusters. QEMU VMs, LXC containers, storage, disks, ZFS, network, firewall, HA (read; plan T2/T3), backups (vzdump to configured storage), tasks, RRD metrics, notifications (event ingest) | **Proxmox Backup Server 4.2+**: read-only first (datastores, snapshots, verify/GC status), then restore-planning helpers. **OpenTofu `bpg/proxmox`** as an optional declarative backend for "desired guest fleet" changes. Web consoles (§6) | Proxmox Datacenter Manager (API still changing after its 1.0 restructure). Ceph management beyond read-only health. SDN authoring (read only in v1). Cluster create/join |

**Version facts.**
- **Verified:**
  - PVE 9.2 is current. x86-64 shipped 2026-05-21 and the first arm64 build shipped 2026-08-05.
  - It runs on Debian 13, Linux 7.0, QEMU 11.0, LXC 7.0 and ZFS 2.4.
  - 9.0 removed `VM.Monitor` and added `VM.Replicate` and `VM.GuestAgent.*`.
  - 9.2 made `VM.PowerMgmt` required to start a guest after create, restore or rollback.
  - 9.2 deprecated `starttime` and `dow` on vzdump jobs in favour of `schedule`.
- **Unverified:** the newest 9.2.x point release, and the exact defaults of the `disks/zfs` parameters.

**Minimum version policy.**
- The adapter reads `GET /version` at connect time. It refuses to register a cluster below 9.0.
- On 9.0–9.1 it warns that the privilege set differs. The bootstrap output in §2.4 targets 9.2.

---

## 2. Credential model

### 2.1 Principles

- **No root, ever.** The harness never holds `root@pam` credentials or a password. It authenticates only with API tokens. The one exception is §6 consoles, post-v1, which use a console-only user.
- **One service user, many tokens.**
  - Service user: `harness@pve`, in the PVE realm, not PAM, so it has no shell login.
  - Each token is **privilege-separated** (`--privsep 1`). The effective rights are the *intersection* of the token's ACLs and the user's ACLs.
  - The user therefore gets the union of the rights, and each token gets only its subset.
- **Blast radius is bounded by ACLs, not by policy alone.** Guests the harness creates go into the pool `agent-managed`. Guest-ops and provision tokens act **only** on `/pool/agent-managed` and the storages they need.
  - Acting on a guest outside the pool requires the owner to add it to the pool. That itself is a T2 plan executed with the provision token on `/pool/agent-managed`. It needs `Pool.Allocate` on the pool and `VM.Allocate` on the guest *(unverified exact privilege)*.
  - Alternatively the owner can grant a wider ACL by hand.
- **Tiered tokens.** A token is chosen from the plan's tier and kind, never by the model. The vault stores each token with its scope metadata. Primary key: `(target_id, capability="proxmox", tier)`.
- **Expiry.**
  - Every token has an `--expire`. The default is 180 days for read, guest-ops and provision.
  - The node-admin token is either **not stored**, with the owner minting it on demand (§2.3), or stored with an expiry of 24 hours or less.
  - The harness raises an `event` 14 days before any token expires.
- **TLS verification is required.**
  - At registration the owner provides the cluster CA (`/etc/pve/pve-root-ca.pem`) or a SHA-256 certificate fingerprint per node.
  - The adapter pins it. `verify=False` is not a supported configuration; a test asserts no code path disables verification.
  - *Implemented as:* a CA bundle is loaded as the only trust store, with hostname checking. A pinned fingerprint is checked in a probe handshake that sends no HTTP bytes. The matching certificate then becomes the **sole trust anchor** of the API connection's context (partial-chain verification, no hostname check, since the pin binds the exact certificate). A node that presents another certificate later is refused by OpenSSL before the token is sent. A mismatch raises `TlsVerificationFailed`, which is a non-retryable `TargetUnavailable`.
  - If the node certificate is ACME or public, the system trust store is accepted.

### 2.2 Tokens and roles

| Token (`harness@pve!…`) | Used for tiers | Role(s) | ACL path(s) | Notes |
|---|---|---|---|---|
| `read` | T0 | `PVEAuditor` (built-in) | `/` (propagate) | Inventory, metrics, tasks, config reads. It cannot read secrets such as cloud-init passwords, because `VM.Config.Cloudinit` is not in Auditor *(unverified for 9.2)*. |
| `guest-ops` | T1, T2 guest ops | custom `HarnessGuestOps` = `VM.Audit VM.PowerMgmt VM.Snapshot VM.Snapshot.Rollback VM.Backup VM.Console Datastore.AllocateSpace Datastore.Audit` | `/pool/agent-managed`, plus each backup storage at `/storage/<id>` | `VM.Console` is included for future console sessions on agent guests only. Rollback carries the privilege, but policy makes it T3. |
| `provision` | T1–T2 create, clone, config, resize, migrate, destroy | custom `HarnessProvision` = `HarnessGuestOps` privileges + `VM.Allocate VM.Clone VM.Config.CDROM VM.Config.CPU VM.Config.Cloudinit VM.Config.Disk VM.Config.HWType VM.Config.Memory VM.Config.Network VM.Config.Options VM.Migrate Datastore.AllocateSpace Datastore.AllocateTemplate SDN.Use Pool.Audit` | `/pool/agent-managed`, `/storage/<guest storages>`, `/sdn/zones/<zone>` or `/sdn` for bridges, `/vms/<template ids>` (`VM.Clone` + `VM.Audit` only, via a separate `HarnessTemplateUser` ACL) | Templates stay outside the pool, so clone needs read and clone rights on the template only. |
| `node-admin` | T3 node work: disks, ZFS, storage add/remove, network apply, firewall, apt, reboot | custom `HarnessNodeAdmin` = `Sys.Audit Sys.Modify Sys.PowerMgmt Sys.Syslog Datastore.Allocate Datastore.Audit` | `/nodes/<node>` per node, `/storage` for storage config | **Minted per approval** (§2.3). Never used by T0–T2 plans. |
| *(none)* | ACL, user and token changes | — | — | The harness **does not hold** `Permissions.Modify` or `User.Modify`. ACL plans (§4.2) produce a preview plus the exact `pveum` commands for the owner to run. |

The privilege lists are the spec target. Validate them with `pveum role add` on 9.2 and record the result. Some privileges can be renamed or split between minor versions *(unverified for 9.2.x)*.

### 2.3 node-admin token lifecycle

The node-admin tier is where mistakes destroy data. The design has two options:

| Option | Flow | Trade-off |
|---|---|---|
| **A, default: owner-minted.** | When a T3 node plan is approved, the CLI asks the owner to paste a node-admin token. It prints the `pveum user token add harness@pve na-<plan_id> --privsep 1 --expire <now+1h>` and `pveum acl modify` commands. The job uses the token once. Afterwards the harness asks the owner to delete it, or it expires on its own. | Safest. One extra step for the owner per T3 node change. |
| **B: stored, short-lived.** | The owner mints a 24-hour token at the start of a maintenance window with `hh proxmox unlock --node pve2 --hours 24`, which prints commands and accepts the token. | Convenient for batches of disk work. The token is encrypted in the vault and auto-forgotten at expiry. |

The token is never exposed to clients or logs, and never reused across plans in option A.

### 2.4 `hh proxmox bootstrap`

`hh proxmox bootstrap --cluster home --nodes pve1,pve2 --guest-storage local-zfs --backup-storage pbs --templates 9000,9001 --bridge vmbr0`

It **prints** a reviewed shell script for the owner to run as root on one cluster node. The harness never executes it. The output is deterministic and covered by a golden-file test:

```sh
# --- generated by hh proxmox bootstrap for cluster home; review before running as root on one node ---
set -euo pipefail
pveum user add harness@pve --comment "AI harness service user (no password, tokens only)"
pveum pool add agent-managed --comment "Guests created and managed by the harness"

# Privilege names target PVE 9.2; renames or splits within 9.2.x are (unverified).
# pveum rejects an unknown privilege, so a mismatch fails here, before any ACL exists.
pveum role add HarnessGuestOps   --privs "VM.Audit VM.PowerMgmt VM.Snapshot VM.Snapshot.Rollback VM.Backup VM.Console Datastore.AllocateSpace Datastore.Audit"
pveum role add HarnessProvision  --privs "VM.Audit VM.PowerMgmt VM.Snapshot VM.Snapshot.Rollback VM.Backup VM.Console VM.Allocate VM.Clone VM.Config.CDROM VM.Config.CPU VM.Config.Cloudinit VM.Config.Disk VM.Config.HWType VM.Config.Memory VM.Config.Network VM.Config.Options VM.Migrate Datastore.AllocateSpace Datastore.AllocateTemplate Datastore.Audit SDN.Use Pool.Audit"
pveum role add HarnessTemplateUser --privs "VM.Audit VM.Clone"
pveum role add HarnessNodeAdmin  --privs "Sys.Audit Sys.Modify Sys.PowerMgmt Sys.Syslog Datastore.Allocate Datastore.Audit"

# User ACLs = union (privsep tokens intersect with these)
# PVEAuditor is expected to exclude VM.Config.Cloudinit, so the read token cannot
# see cloud-init secrets (unverified for 9.2).
pveum acl modify /                    --users harness@pve --roles PVEAuditor
pveum acl modify /pool/agent-managed  --users harness@pve --roles HarnessProvision
pveum acl modify /storage/local-zfs   --users harness@pve --roles HarnessProvision
pveum acl modify /storage/pbs         --users harness@pve --roles HarnessGuestOps
pveum acl modify /sdn/zones/localnetwork --users harness@pve --roles HarnessProvision   # bridge use (unverified path for vmbr0)
pveum acl modify /vms/9000            --users harness@pve --roles HarnessTemplateUser
pveum acl modify /vms/9001            --users harness@pve --roles HarnessTemplateUser
pveum acl modify /nodes/pve1          --users harness@pve --roles HarnessNodeAdmin
pveum acl modify /nodes/pve2          --users harness@pve --roles HarnessNodeAdmin

# Tokens (privilege-separated, expiring). Copy each secret into `hh proxmox token set`.
EXP=$(date -d '+180 days' +%s)
pveum user token add harness@pve read      --privsep 1 --expire "$EXP"
pveum user token add harness@pve guest-ops --privsep 1 --expire "$EXP"
pveum user token add harness@pve provision --privsep 1 --expire "$EXP"
pveum acl modify /                   --tokens 'harness@pve!read'      --roles PVEAuditor
pveum acl modify /pool/agent-managed --tokens 'harness@pve!guest-ops' --roles HarnessGuestOps
pveum acl modify /storage/pbs        --tokens 'harness@pve!guest-ops' --roles HarnessGuestOps
pveum acl modify /pool/agent-managed --tokens 'harness@pve!provision' --roles HarnessProvision
pveum acl modify /storage/local-zfs  --tokens 'harness@pve!provision' --roles HarnessProvision
pveum acl modify /sdn/zones/localnetwork --tokens 'harness@pve!provision' --roles HarnessProvision
pveum acl modify /vms/9000           --tokens 'harness@pve!provision' --roles HarnessTemplateUser
pveum acl modify /vms/9001           --tokens 'harness@pve!provision' --roles HarnessTemplateUser
# node-admin tokens are NOT created here; they are minted per approved plan (see §2.3).

# TLS pin: paste this into `hh proxmox register --ca-file`
cat /etc/pve/pve-root-ca.pem
```

After the owner pastes the tokens, `hh proxmox verify` calls `GET /access/permissions` with each token. It asserts the effective permissions **exactly** match the expected matrix: no missing privileges, **and no extra ones**. Tokens with too much privilege are refused, with an explanation.

---

## 3. Adapter

`capabilities/proxmox/adapter.py`: typed, async, no policy, no database. Inputs are a target config and a token. It returns pydantic models.

| Concern | Spec |
|---|---|
| **Transport** | `httpx.AsyncClient` with HTTP/1.1 (pveproxy), base `https://<node>:8006/api2/json`, header `Authorization: PVEAPIToken=harness@pve!<id>=<secret>`. TLS is pinned per §2.1. No cookies or tickets (except §6). |
| **Timeouts** | Connect 5 s, read 30 s by default; 120 s for `disks/list` with SMART and for `GET /nodes/{n}/apt/update`. Write calls that return a UPID must return within 30 s. A read timeout on such a call is **ambiguous**: see error mapping. |
| **Node routing** | A cluster has several API endpoints, one per node. Reads go to any healthy node. A write about node X goes to node X if reachable; otherwise to any node, since pveproxy proxies. UPID polling always goes to the node encoded in the UPID. |
| **UPID** | Parse `UPID:<node>:<pid hex>:<pstart hex>:<starttime hex>:<type>:<id>:<user>:` into a typed `Upid`. Poll `GET /nodes/{node}/tasks/{upid}/status` with backoff of 1 s, 2 s, 4 s, then every 5 s until `status == "stopped"`. Read `exitstatus`: `OK` maps to success; `WARNINGS: n` maps to success with warnings recorded; anything else maps to a failure with that text. Fetch logs with `GET .../tasks/{upid}/log?start=N&limit=500`, incrementally. Logs are stored truncated to 64 KB and redacted (§9). |
| **Optimistic concurrency** | Guest config reads keep `digest`. Every config write passes `digest=<planned digest>`. Proxmox rejects the write if the config changed in between. The adapter maps that rejection to `StaleState`; the job's outcome is `cancelled (stale plan)`. Node network config also has a digest; use it the same way. |
| **Locks** | Guest config `lock` values (`backup`, `migrate`, `snapshot`, `snapshot-delete`, `clone`, `rollback`, `create`, `disk`, `suspended`) make preflight fail with `TargetLocked`. **The adapter never calls `unlock` and no tool offers it.** Clearing a lock is an owner action, shown as advice in the preview. Storage lock timeouts ("can't lock file", HTTP 500) map to `TargetBusy`. Retry them only if the call is a read or the plan step is declared idempotent. |
| **Write serialization** | In-process async locks keyed by `node` and by `storage`: one write per node and one per storage at a time. DBOS queues with concurrency 1 per key give the same guarantee across restarts. Reads are not serialized. |
| **VMID allocation** | `GET /cluster/nextid` is racy. The planner proposes a VMID. The executor creates with that VMID. If Proxmox reports the VMID exists, the step does not retry blindly: it reads `/cluster/resources`. If the VMID belongs to a guest whose `tags` contain `harness-plan-<plan_id>`, the step is treated as **already done** (idempotent replay). Otherwise it fails with `StaleState`, and the owner re-plans. |
| **Idempotency tags** | Every guest the harness creates gets the tags `harness` and `harness-plan-<plan_id short>` and a description footer `managed-by: harness plan <plan_id>`. That lets a replayed create step detect its own earlier success. |
| **Error mapping** to shared exceptions (`homelab_harness_sdk.errors`) | **Implemented for reads:** `401` → `AuthRejected`, not retryable (the only error that may mark a token unusable, R-14). `403` → `PermissionDenied`, not retryable. `404`, `501`, or `500` with "does not exist"/"no such" → `NotFound`. `500` with "can't lock file"/"is locked"/"locked", `500` with "already exists", or `409` → `Conflict`. `429` → `RateLimited` with `Retry-After`. `400` and other 4xx → `InvalidInput`. `595` (pveproxy cannot reach the node), other 5xx, connect errors, and read timeouts on a `GET` → `TargetUnavailable`, retryable. A 2xx with an unreadable body → `UnexpectedResponse`. PVE's error text is used only to classify; `safe_message` names the call and status, never the response body or reason. **Planned for writes:** read timeout or 5xx on a write → `AmbiguousOutcome`, never retried; the job outcome becomes `uncertain` unless verification can prove the result either way. The spec's earlier finer-grained names (`TargetLocked`, `TargetBusy`, `StaleState`) map onto `Conflict` until the SDK grows them. |
| **Retries** | Reads: up to 3 attempts with jittered backoff, only on `TargetUnreachable`, `TargetBusy`, or 502/503. Writes: none at the adapter. The executor decides per step, from the step's declared idempotency (§4.3). |
| **Typed models** | *Implemented:* `Version`, `ClusterStatusEntry`, `Resource`, `NodeSummary`, `NodeStatus`, `RrdPoint`, `Guest`, `GuestConfig`, `GuestStatus`, `StorageConfig`, `StorageStatus`, `StorageVolume`, `Disk`, `SmartData`, `NetworkConfig`, `Pool`, `Task`, `TaskStatus` (with `outcome`), `TaskLog`, `HaStatusEntry`, `BackupJob`; lists come back as `Listing` with `as_of`. Unknown fields are kept in `model_extra`. *Planned:* `Node`, `Guest` (vmid, type `qemu`/`lxc`, name, node, status, tags, pool, lock, template, ha state), `GuestConfig` (raw dict + digest + typed common fields), `Storage`, `Disk` (devpath, by-id path, serial, model, size, type, wearout, health, used-by), `ZfsPool`, `NetIface`, `FwRule`, `HaResource`, `BackupJob`, `Task`, `RrdPoint`. Unknown fields are preserved in `extra`, not dropped. |
| **Not in the adapter** | Policy, tier decisions, previews, DB access, notification. The adapter is fully covered by recorded-fixture tests (§9). |

---

## 4. Tool catalog

Conventions:
- Tool names are `proxmox.<area>.<verb>`.
- All read tools carry `readOnlyHint: true`.
- Plan tools carry `readOnlyHint: true` too, because **creating a plan changes nothing**. They return `{plan_id, tier, approval: auto|required, preview, expires_at}`.
- Apply happens only after approval, via the job engine. Clients can watch with `proxmox.job.get` or the `job://{id}` resource.
- Every tool takes `cluster` (default: the only one registered) and returns `as_of` on inventory-derived data.

### 4.1 Read tools (T0)

**Adapter coverage (implemented, mocked; not yet verified live).** The tools marked *implemented* below are served over MCP. `ProxmoxClient` reads these endpoints: `/version`, `/cluster/status`, `/cluster/resources`, `/cluster/tasks`, `/cluster/ha/status/current`, `/cluster/backup`, `/pools`, `/storage`, `/nodes`, and per node `status`, `rrddata`, `network`, `{qemu,lxc}` lists, `{qemu,lxc}/{id}/{config,status/current}`, `storage/{s}/{status,content}`, `disks/list`, `disks/smart`, `tasks`, and `tasks/{upid}/{status,log}` (routed to the node in the UPID). Still to add: `apt/update`, snapshots, guest agent, ZFS, firewall, HA resources and rules, and guest or storage RRD.

| Tool | Returns | Source |
|---|---|---|
| `proxmox.cluster.list` | Registered clusters, nodes, quorum, version. *Implemented.* Lists every registered cluster. One that cannot be read is reported with `reachable: false` and an owner-safe `error`, not as a failed call. | `/cluster/status`, `/version` |
| `proxmox.cluster.resources` | All guests, storages, and nodes with usage, filterable by `type`, `node`, `pool`, `tag`. *Implemented.* `type` is filtered by PVE; `node`, `pool` and `tag` are filtered by the harness. | `/cluster/resources` |
| `proxmox.node.list` | *Implemented.* Nodes with online status, CPU, memory, disk, uptime and certificate fingerprint | `/nodes` |
| `proxmox.node.get` | CPU, memory, uptime, kernel, PVE version, subscription state, pending apt updates count. *Implemented,* without the subscription state or the pending-updates count (the adapter does not read `apt/update` yet). | `/nodes/{n}/status`, `/nodes/{n}/apt/update` (cached list only; no refresh) |
| `proxmox.guest.list` / `.get` | Guest summary; `.get` adds config (secrets redacted), snapshots, HA state, backup recency, and pool. *Implemented.* `.get` resolves the node and type from `/cluster/resources` when they are omitted. It returns status, HA state, the config digest, and the masked config; snapshots and backup recency are not included yet. `.list` without a node reads every online node, and reports the nodes that fail in `unreachable_nodes`. | `/nodes/{n}/{qemu,lxc}/{id}/{status/current,config,snapshot}` |
| `proxmox.guest.agent_info` | QEMU guest agent: OS info, IPs, filesystems (read-only agent calls only) | `.../agent/{get-osinfo,network-get-interfaces,get-fsinfo}` |
| `proxmox.storage.list` / `.content` | Storages with type, usage, and content types; volumes on a storage. *Implemented.* | `/storage`, `/nodes/{n}/storage/{s}/{status,content}` |
| `proxmox.storage.status` | *Implemented.* One storage's usage on one node | `/nodes/{n}/storage/{s}/status` |
| `proxmox.pool.list` | *Implemented.* Resource pools; with `pool`, its members. Comments are untrusted | `/pools` |
| `proxmox.disk.list` | Physical disks: devpath, **by-id path**, serial, model, size, wearout, health, `used` (partitions, LVM, ZFS, Ceph, mounted). This answers "which disks are new and empty?". *Implemented.* | `/nodes/{n}/disks/list?include-partitions=1` |
| `proxmox.disk.smart` | SMART attributes and health for one disk. *Implemented.* The SMART `text` (NVMe, SAS) is untrusted. | `/nodes/{n}/disks/smart?disk=` |
| `proxmox.zfs.list` / `.get` | Pools, layout, health, errors, scrub status | `/nodes/{n}/disks/zfs[/{name}]` |
| `proxmox.network.list` | Interfaces and bridges, **including pending changes** (`interfaces.new` diff). *Implemented,* with `has_pending_changes` and the diff (untrusted). | `/nodes/{n}/network` |
| `proxmox.firewall.get` | Cluster, node, and guest rules, options, aliases, ipsets | `/cluster/firewall/*`, `/nodes/{n}/firewall/*`, `.../{id}/firewall/*` |
| `proxmox.ha.status` | HA manager status, resources, rules or groups. *Implemented* for `status/current` only; resources and rules are not read yet. | `/cluster/ha/{status/current,resources,rules}` *(9.x uses rules; groups are legacy, unverified)* |
| `proxmox.backup.jobs` / `.recent` | Backup jobs and schedules; last result per guest, from task history. *Implemented* for `.jobs`; `.recent` is `proxmox.task.list` with `type: vzdump` for now. | `/cluster/backup`, `/nodes/{n}/tasks?typefilter=vzdump` |
| `proxmox.task.list` / `.get` | Recent tasks, or one task with log excerpt. *Implemented.* The status text and log lines are untrusted; `.get` returns a log window (`log_start`, `log_limit` up to 500). | `/cluster/tasks`, `/nodes/{n}/tasks/{upid}/{status,log}` |
| `proxmox.metrics.rrd` | Time series for node, guest, or storage over `hour`/`day`/`week`/`month`/`year`, `cf=AVERAGE` or `MAX`. *Implemented* for nodes; guest and storage series are not read yet. | `/nodes/{n}/rrddata`, `.../{id}/rrddata`, `/nodes/{n}/storage/{s}/rrddata` |
| `proxmox.capacity.check` | Deterministic helper: can node X fit cores/memory/disk Y on storage Z? Returns headroom and the reasoning | Inventory plus live status |
| `proxmox.job.get` / `.list` | Harness jobs for Proxmox plans: steps, UPIDs, outcome, verification | Core jobs tables |

### 4.2 Plan tools

**Tier floors are set in code** (see [safety-model.md](../safety-model.md)). Config can raise a tier but never lower it below the floor. "Default" is the tier for the common case. The policy table can escalate it from context: a guest outside the pool, the guest that runs the harness itself, a node that holds the harness, or a running HA resource.

| Tool → plan kind | Default / floor | Preflight (at plan **and** apply time) | Preview shows | Executor steps | Verification | Rollback note |
|---|---|---|---|---|---|---|
| `guest.plan_power` → `guest.start` / `shutdown` / `reboot` / `stop` | T1 / T1 (`stop` is a hard stop: T2) | Guest in the pool (else T2); not locked; not the harness host (else T3); HA-managed → use an HA state change instead | Current to target state, HA note, "hard stop may lose data" for `stop` | `POST .../status/{action}` → UPID → poll | `status/current` matches the target | The inverse power action |
| `guest.plan_snapshot` → `snapshot.create` | T1 / T1 | Not locked; storage supports snapshots; `vmstate` only if requested and there is space | Snapshot name (`harness-<date>-<slug>`), include RAM yes/no, storage cost estimate | `POST .../snapshot` → UPID | The snapshot is listed | `snapshot.delete` |
| `guest.plan_snapshot_rollback` → `snapshot.rollback` | T3 / T3 | Snapshot exists; age shown; guest not locked | **Data written since the snapshot will be lost.** Shows snapshot age, whether the guest will restart (`start=1` needs `VM.PowerMgmt`), and other snapshots that become orphaned | Optional pre-rollback snapshot (default **on**: `harness-pre-rollback-<plan>`), then `POST .../snapshot/{s}/rollback` → UPID | Config digest and status as expected | Roll back to the pre-rollback snapshot |
| `guest.plan_snapshot_delete` → `snapshot.delete` | T2 / T2 | Snapshot is not the current parent of other snapshots, or the cascade is shown | Snapshot name, age, space reclaimed estimate | `DELETE .../snapshot/{s}` → UPID | Snapshot gone | None (irreversible); preview says so |
| `guest.plan_create` → `guest.create_from_template` | T1 (in the pool, within capacity) / T1 | Template exists and is readable; VMID free; capacity check passes; storage has space; bridge exists; cloud-init fields valid; SSH keys look like public keys | Template name and OS, VMID, node, storage, cores/memory/disk, NIC/bridge/VLAN, cloud-init user, keys (fingerprints only), IP config, pool `agent-managed`, tags, start-after-create, capacity before and after | Clone (`POST /nodes/{n}/qemu/{tpl}/clone`, `full=1`, `pool`, `target`, `storage`) → UPID; `PUT/POST .../config` (cores, memory, `ciuser`, `sshkeys` URL-encoded, `ipconfig0`, tags, description) with digest; `PUT .../resize` if larger; optional start | Config matches the plan; status running (if started); guest agent reports an IP within 3 min (warning, not failure, if the agent is absent) | `guest.destroy` of the created VMID |
| `guest.plan_create_lxc` → `lxc.create` | T1 / T1 | OS template exists on storage; unprivileged by default (**privileged = T3** and needs `Sys.Modify`, so it is refused with the provision token); capacity check | As above, plus `unprivileged=1`, features (nesting), mount points | `POST /nodes/{n}/lxc` → UPID → optional start | Config and status | `guest.destroy` |
| `guest.plan_clone` → `guest.clone` | T1 / T1 | Source readable; source in the pool or a template; capacity | Full or linked, target storage, new VMID, name | `POST .../clone` → UPID | New guest exists with tags | `guest.destroy` |
| `guest.plan_config` → `guest.config_change` | T2 / T2 (T1 for name, tags, description only) | Digest captured; hot-plug vs reboot-required computed | **Field-by-field diff** (current to proposed); reboot-required yes/no; pending changes already present | `PUT .../config` with `digest` (synchronous) or `POST` (async → UPID) | Config equals the plan (pending section empty, or pending as expected) | Inverse diff, shown as a ready plan |
| `guest.plan_resize` → `disk.resize` | T2 / T2 | Grow only (**shrink is refused**: Proxmox can't shrink); storage space | Disk, old to new size, "filesystem inside the guest must be grown separately" | `PUT .../resize` (sync or UPID) | Size matches | None (irreversible); preview says so |
| `guest.plan_migrate` → `guest.migrate` | T2 / T2 (T3 if HA-managed, or with local disks over 200 GB) | Target node online with capacity; storage mapping valid; local disks/CD-ROMs/mapped devices listed; `/nodes/{n}/{qemu}/{id}/migrate` precondition `GET` (local resources) | Online or offline, expected downtime class, data to copy, target storage | `POST .../migrate` → UPID (long; poll with a progress log) | Guest is on the target node with the same status | Migrate back (shown as a plan) |
| `guest.plan_destroy` → `guest.destroy` | T3 / T3 | Guest in the pool (**outside the pool: refused**, the owner must move it in first); `protection` not set (if set: refused, with advice); HA/replication membership listed; **last backup age** | Name, tags, disks and sizes, last backup and age (**warning if none in 7 days**), HA/replication, `purge` and `destroy-unreferenced-disks` flags, firewall/ipset references | Optional final backup (default **on** if no backup in 24 h) → stop → `DELETE .../{id}?purge=1&destroy-unreferenced-disks=1` → UPID | Guest absent from `/cluster/resources`; volumes absent | "Restore from backup <id>", if a backup exists; otherwise "none" |
| `backup.plan_now` → `backup.run` | T1 / T1 | Storage reachable with space; guest not locked | Mode (snapshot/suspend/stop), compression, storage, retention effect (prune) | `POST /nodes/{n}/vzdump` → UPID | Task OK; archive listed | Delete the archive (T2) |
| `backup.plan_restore` → `backup.restore` | T3 / T3 when it overwrites an existing VMID; T2 when restoring to a new VMID | Archive exists; target VMID state; **config diff archive vs current** | Archive date, size, target VMID, overwrite yes/no, config diff, `unique` (new MACs) | `POST /nodes/{n}/qemu` with `archive=`, `force=` (overwrite only), `pool` → UPID | Guest exists with the expected config | For an overwrite: a pre-restore backup (default on) |
| `disk.plan_wipe` → `disk.wipe` | T3 / T3 | Disk not mounted, not in ZFS/LVM/Ceph, not the boot disk; owner confirms the **serial** | Device by-id, serial, model, size, SMART health, partitions and signatures found | `PUT /nodes/{n}/disks/wipedisk` → UPID | `disks/list` shows `used` = none | None (irreversible) |
| `disk.plan_initgpt` → `disk.initgpt` | T3 / T3 | Same as wipe | Same | `POST /nodes/{n}/disks/initgpt` → UPID | GPT present | None |
| `zfs.plan_pool` → `zfs.create` | T3 / T3 | All disks **empty** (no partitions, signatures, mounts, or pool/LVM/Ceph use), healthy SMART, same node; name free; ashift; layout valid for the disk count | Devices (by-id, serial, size), **layout and redundancy** (stripe = **none**), usable capacity, ashift, compression, `add_storage` and storage ID, the **exact API call or command** | Layouts other than stripe: `POST /nodes/{n}/disks/zfs` (`raidlevel` ∈ `single, mirror, raid10, raidz, raidz2, raidz3, draid, draid2, draid3`). **Stripe:** see §5 | `zfs.get` shows the layout and health ONLINE; storage registered if requested | `zpool destroy <name>` (T3 plan); data loss if already used |
| `storage.plan_add` / `plan_remove` → `storage.add` / `.remove` | T2 add / T3 remove | Remove: list guests and backups on that storage (**refused if any guest disk lives there**) | Storage config diff (`/etc/pve/storage.cfg` semantics), content types, nodes | `POST /storage` or `DELETE /storage/{id}` (sync) | Storage listed or absent | The inverse plan |
| `network.plan_change` → `network.apply` | T3 / T3 | Pending changes already on the node: **refused** until the owner reviews or reverts them; the management interface or the bridge carrying the node IP is detected | **Diff of `interfaces` vs `interfaces.new`**; a **MANAGEMENT INTERFACE CHANGE** banner if relevant; the auto-revert plan | (1) stage via `POST/PUT /nodes/{n}/network[/{iface}]`, (2) show the staged diff again at apply time, (3) `PUT /nodes/{n}/network` (ifreload) → UPID, (4) **dead-man check**: within 90 s, confirm reachability via API and the linux capability. If unreachable, the linux capability's out-of-band SSH path restores the previous `/etc/network/interfaces` and runs `ifreload -a` *(requires a pre-staged revert script; see the linux-docker spec)* | API reachable; interface state matches | Automatic (dead-man), or `DELETE /nodes/{n}/network` before apply to discard staged changes |
| `network.plan_revert_pending` → `network.revert` | T1 / T1 | Pending changes exist | The diff being discarded | `DELETE /nodes/{n}/network` | No pending changes | — |
| `firewall.plan_rules` → `firewall.change` | T2 (guest level, guest in pool) / T3 (node or cluster level, or enabling the firewall) | **Lockout check:** simulate the resulting ruleset for the harness's source IP and the owner's tailnet range on TCP 8006 and 22 → refused if either would be blocked | Rule diff (position, action, proto, ports, source/dest), enable/disable changes, lockout check result | Rule POST/PUT/DELETE with `digest`; enabling the firewall happens **last** | Rules equal the plan; API still reachable | Inverse rule diff (auto-applied if the post-apply reachability check fails) |
| `ha.plan_change` → `ha.change` | T2 (add/remove an agent-pool guest) / T3 (cluster `disarm-ha`/`arm-ha`, rules, fencing-relevant changes) | Quorum OK; resource state | Resources affected, fencing implications | `/cluster/ha/resources` CRUD; 9.2 `disarm-ha`/`arm-ha` *(endpoint names unverified)* | HA status matches | Inverse change |
| `access.plan_change` → `access.change` | T3 / T3 | — | **Privilege delta per path** (before vs after effective permissions); a **warning** if anything reaches `Administrator`, `Sys.Modify`, `Permissions.Modify`, or path `/` | **Not executed by the harness.** The job renders the exact `pveum` commands and waits for the owner to run them and click "done". Then `hh proxmox verify` re-checks the permission matrix | Effective permissions as planned | Inverse `pveum` commands |
| `console.plan_session` → `console.open` | T3 / T3 | Target exists; console user configured | Target, user, TTL (default 15 min), recording on, "this bypasses API policy" banner | Post-v1 (§6) | — | Session ends at TTL |
| `node.plan_reboot` → `node.reboot` | T3 / T3 | Guests on the node and their HA state; quorum after the node leaves; the harness host is on this node → refused unless `--allow-self` | Guests that will stop or migrate, HA behaviour, expected downtime | Optional: migrate or shut down guests (sub-steps) → `POST /nodes/{n}/status` `command=reboot` → wait for the node to come back (poll `/nodes/{n}/status`, 15 min max) | Node online; guests' state restored per the plan | None; shown |
| `node.plan_upgrade` → `node.apt_upgrade` | T3 / T3 | `apt/update` list refreshed (a T1 sub-step); kernel change detected → reboot plan suggested; no PVE major-version jump | Package list with old and new versions, kernel change, `pve-manager` change, "reboot required" | Run `apt-get dist-upgrade -y` via the **linux** capability (Proxmox's API has no non-interactive upgrade; the GUI uses a console) → capture output | `apt/versions` shows the target versions | None (snapshotting the root filesystem is out of scope); preview says so |

### 4.3 Executor rules (all plan kinds)

- **One DBOS step per external call.** Each step declares `idempotency`:
  - `read`: retry freely.
  - `idempotent`: retry is safe, for example a config `PUT` with `digest`, or a create that is detectable by its tag.
  - `unsafe`: never re-executed after an ambiguous result.
- **Persist the UPID first.** A step that starts a Proxmox task persists the UPID **before** polling. On restart, the job resumes polling the stored UPID instead of re-issuing the call.
- **Apply-time preflight.** It re-reads live state and compares it with the plan's `observed` snapshot: digests, disk `used`, guest status, pending network changes. Any difference outside the plan's own effect gives `cancelled (stale plan)`.
- **Verification is mandatory.** A job whose actions succeeded but whose verification failed ends `uncertain` with both results. It never reports `succeeded`.
- **Never chain unapproved writes.** Composite plans list every sub-step in the preview, for example "final backup → stop → destroy". The approval covers the whole list and nothing else.

---

## 5. Worked example: "I added two drives, make them a ZFS stripe"

### 5.1 Conversation

1. **The client reads:** `proxmox.disk.list(node="pve2")`. The two new disks show `used: null`, no partitions, health PASSED, wearout 100%. The steering skill tells the model to confirm which disks by serial, never by `/dev/sdX`.
2. **The client plans:** `proxmox.zfs.plan_pool(node="pve2", name="tank-fast", layout="stripe", disks=["ata-SAMSUNG_MZ7L31T9HBLT-00A07_S6ESNX0W123456","ata-SAMSUNG_MZ7L31T9HBLT-00A07_S6ESNX0W654321"], ashift=12, compression="lz4", add_storage=True, storage_id="tank-fast")`.
3. **The harness answers** with plan `p_7f3c`. It is tier T3, needs approval, and requires a typed confirmation of `tank-fast`. The preview is in §5.3. The client relays: "Approval sent to your phone. Note that a stripe has no redundancy: one disk failure loses the pool."

### 5.2 Plan document (schema)

```python
class ZfsDevice(BaseModel):
    by_id: str            # /dev/disk/by-id/ata-..., the ONLY identifier used in commands
    serial: str
    model: str
    size_bytes: int
    smart_health: Literal["PASSED", "FAILED", "UNKNOWN"]
    wearout_pct: int | None
    observed_used: None   # preflight requires None; the plan stores what was observed

class ZfsCreateParams(BaseModel):
    node: str
    name: constr(pattern=r"^[a-z][a-z0-9_-]{1,30}$")
    layout: Literal["stripe","single","mirror","raid10","raidz","raidz2","raidz3","draid","draid2","draid3"]
    devices: conlist(ZfsDevice, min_length=1)
    ashift: conint(ge=9, le=16) = 12
    compression: Literal["on","off","lz4","zstd","gzip","lzjb","zle"] = "lz4"
    add_storage: bool = True
    storage_id: str | None

class Plan(BaseModel):              # shared shape, see safety-model.md
    id: str                         # p_<ulid>
    kind: Literal["zfs.create"]
    capability: Literal["proxmox"]
    target: TargetRef               # cluster=home, node=pve2
    params: ZfsCreateParams
    observed: dict                  # live facts captured at plan time (disks/list rows, pool names)
    preflight: list[CheckResult]    # name, passed, detail
    tier: Literal["T3"]
    approval: ApprovalSpec          # required=True, typed_confirmation="tank-fast", expires_in=900s
    steps: list[StepSpec]           # ordered; each has idempotency + credential tier
    preview: Preview                # rendered text + structured diff
    rollback: str
    created_by: ClientRef           # client name + MCP session id + owner
    created_at: datetime
    hash: str                       # sha256 over canonical JSON of everything above except hash
```

The `steps` for a stripe:

| # | Step | Capability, credential | Idempotency |
|---|---|---|---|
| 1 | `preflight.recheck`: `disks/list` + `zfs.list` + `blkid`/`wipefs -n` per device over SSH | proxmox `read` + linux `read` | read |
| 2 | `zpool.create`: `zpool create -o ashift=12 -O compression=lz4 -O atime=off -m /tank-fast tank-fast /dev/disk/by-id/…123456 /dev/disk/by-id/…654321` as a fixed argv template, no shell | linux `node-admin` sudoers entry for `/usr/sbin/zpool create` only | unsafe; replay detection: if `zpool list -H -o name tank-fast` exists with exactly these vdevs, the step counts as done |
| 3 | `storage.add`: `POST /storage` `type=zfspool, storage=tank-fast, pool=tank-fast, content=images,rootdir, nodes=pve2` | proxmox `node-admin` (minted per §2.3) | idempotent (exists with identical config means done) |
| 4 | `verify`: `GET /nodes/pve2/disks/zfs/tank-fast` (health ONLINE, 2 vdevs, no redundancy), `GET /storage/tank-fast` | proxmox `read` | read |

**Why SSH for a stripe.** Proxmox's `POST /nodes/{n}/disks/zfs` has no RAID0 or stripe raidlevel. `single` takes exactly one disk. The supported route is a raw `zpool create` with several top-level vdevs, followed by registering the storage. The plan says this in plain words. It never pretends Proxmox offered a stripe. For every other layout the executor uses the API, with `raidlevel` and `devices` set to the by-id paths.

### 5.3 Preview (what the phone and CLI show)

```
PLAN p_7f3c · zfs.create · pve2 · TIER 3 (destructive, needs typed confirmation)

Create ZFS pool "tank-fast" as a STRIPE across 2 disks.
⚠ NO REDUNDANCY: if either disk fails, ALL data in this pool is lost.
  Use "mirror" instead for redundancy (usable 1.9 TB instead of 3.8 TB).

Devices (both verified empty: no partitions, no signatures, not mounted, not in ZFS/LVM/Ceph):
  /dev/disk/by-id/ata-SAMSUNG_MZ7L31T9HBLT-00A07_S6ESNX0W123456  1.92 TB  SMART PASSED  wear 100%
  /dev/disk/by-id/ata-SAMSUNG_MZ7L31T9HBLT-00A07_S6ESNX0W654321  1.92 TB  SMART PASSED  wear 100%

Result: usable ≈ 3.8 TB · ashift=12 · compression=lz4 · mounted at /tank-fast
Then register Proxmox storage "tank-fast" (images, rootdir) on pve2.

Proxmox's API has no stripe level, so the harness will run exactly:
  zpool create -o ashift=12 -O compression=lz4 -O atime=off -m /tank-fast tank-fast \
    /dev/disk/by-id/ata-…S6ESNX0W123456 /dev/disk/by-id/ata-…S6ESNX0W654321

Rollback: zpool destroy tank-fast (only safe before data is written).
Credentials: linux node-admin (zpool create only), proxmox node-admin (minted for this plan).
Requested by: Claude Code (session 3f1a…) · expires in 15 min
To approve, type the pool name: tank-fast
```

### 5.4 Approval and job

- **The ntfy notification** carries the title and the first lines, with the actions **[Review & approve]**, which opens a CLI deep link or the UI later, and **[Reject]**.
  - T3 can't be approved from a single button. The owner runs `hh approve p_7f3c` and types `tank-fast`, or uses the UI later.
  - For §2.3 option A, the CLI then asks for the node-admin token.
- **The approval is claimed once** and bound to the plan hash. The job starts with DBOS workflow ID `p_7f3c`.
- **An ntfy summary arrives on completion:** "tank-fast created (stripe, 3.8 TB, ONLINE). Storage registered." It includes the job link.

### 5.5 Failure modes and outcomes

| Situation | Detected by | Outcome |
|---|---|---|
| A disk got a partition between plan and apply (owner was doing something by hand) | Step 1 recheck | `cancelled (stale plan)`, with the diff of what changed |
| A disk's by-id path is gone (cable or slot moved) | Step 1 | `cancelled (stale plan)` |
| `zpool create` returns non-zero (for example, a device busy) | Step 2 exit code; stderr redacted into the job | `failed`; the step's replay check confirms no pool exists |
| SSH drops or times out during `zpool create` | Step 2 | **Ambiguous** → replay check: pool exists with these vdevs → continue. Pool exists with **different** vdevs, or `zpool status` errors → `uncertain`, ntfy to the owner, no further steps |
| Harness restarts after step 2 | DBOS resumes at step 3 | Normal continuation (step 3 is idempotent) |
| `POST /storage` returns 403 (expired node-admin token) | Step 3 | `failed` at step 3, with the pool created and storage not registered. The preview of the follow-up plan `storage.add` is offered |
| Verification shows DEGRADED or a missing vdev | Step 4 | `uncertain`, with `zpool status` attached |
| Approval not given within 15 min | Approval expiry | `expired`; a new plan is needed |
| The approval is replayed (double click, retried callback) | Single-claim | The second claim is rejected; the job runs once |

---

## 6. Consoles (decision: post-v1, with this design)

**Decision.** v1 has **no** web or CLI console proxy. The reason:
- Proxmox rejects API-token-issued VNC tickets at `vncwebsocket`. Only a session ticket works.
- A session ticket needs a password-based user and a cookie-plus-CSRF session, which is a new credential class with its own threat model.
- A console session also bypasses the API policy entirely.

**v1 alternatives:**
- `hh ssh <host>` delegates to the owner's own `ssh` over Tailscale. The harness only resolves the address from inventory.
- The Proxmox web UI remains available for consoles.

There is a pending pdm-devel patch for token-owned VNC tickets (Nov 2025). Whether it has merged is unverified. If it merges, re-evaluate.

**Post-v1 design:**

| Element | Spec |
|---|---|
| Console user | `harness-console@pve`: realm PVE, a strong random password stored in the vault, role `HarnessConsole` = `VM.Console` on `/pool/agent-managed` (and `Sys.Console` on `/nodes/<n>` only if node shells are wanted, as a separate opt-in). No other privileges. |
| Ticket | `POST /access/ticket` gives `PVEAuthCookie` + `CSRFPreventionToken`, valid for 2 h. Fetched per session, kept in memory only, never sent to the browser. |
| Flow | `POST /nodes/{n}/{qemu\|lxc}/{id}/termproxy` (or `/nodes/{n}/termproxy`) returns `port`, `ticket`, `user`. Then the backend opens `wss://{n}:8006/api2/json/nodes/{n}/{…}/vncwebsocket?port=&vncticket=` with the cookie. It sends `user:ticket\n` first, then relays the xterm.js protocol (`0:<len>:<data>` input, `1:<cols>:<rows>` resize, `2` ping) between the browser WebSocket and Proxmox. |
| Policy | Opening a session is a `console.open` plan, T3. TTL is 15 min by default, 60 max, with an idle timeout of 5 min. **Agents can never open consoles**: there is no MCP tool. Only the owner, from the UI or CLI, can open one. |
| Recording | The proxy records every session server-side as asciicast v2: input and output, with a timestamp per frame. Recordings are stored encrypted, linked from the audit event, and retained 30 days by default. The browser can't disable recording. |
| UI | Multiple panes (dockview) in the web UI; see [ui-vision.md](../ui-vision.md). |

---

## 7. Events

**Ingest path.** PVE notification system → webhook target → `POST https://harness.<tailnet>/events/proxmox/<cluster>`.

| Element | Spec |
|---|---|
| Endpoint | Tailnet only, never on the public tunnel. It requires header `X-Harness-Event-Secret: <per-cluster random secret>`, compared in constant time. The body is limited to 64 KB. |
| PVE config (printed by `hh proxmox events setup`) | `POST /cluster/notifications/endpoints/webhook`: name `harness`, method POST, URL above, header with the secret (stored as a webhook secret, root-only on the PVE side), Handlebars body `{"title":"{{ title }}","message":"{{ escape message }}","severity":"{{ severity }}","fields":{{ json fields }},"ts":"{{ timestamp }}"}` *(template helpers unverified for 9.2)*. Matcher `harness-all`: `mode=any`, severity ≥ info, target `harness`. |
| Dedupe | Key = sha256(cluster + `fields.type` + `fields.hostname` + `fields.job-id` + title + timestamp truncated to the minute), unique in `events`. |
| Handling | Each event: (1) stored redacted, (2) triggers a targeted inventory refresh (for example, a backup finished → refresh backup recency), (3) is routed by policy to ntfy. |
| Example routes | `vzdump` with `severity=error` → ntfy priority high: "Backup of web-01 failed on pve1 (last good backup: 3 days ago)", with the action **[Show task log]**. `replication` error → high. `package-updates` → low, batched daily. ZFS events (ZED via PVE notifications) such as `DEGRADED` or `checksum errors` → **urgent**, with the action **[Plan scrub]**, which creates a T1 `zfs.scrub` plan *(the scrub tool is a small v1.x addition)*. Fencing → urgent. |
| Steering hook | Events are exposed as the resource `proxmox://cluster/{name}/events?since=` so a client can say "what went wrong overnight?" with sourced answers. |

---

## 8. MCP resources and prompts

**Resources** (all read-only; JSON with a text rendering; `as_of` on each):

| URI | Content |
|---|---|
| `proxmox://clusters` | Registered clusters and nodes |
| `proxmox://cluster/{name}/inventory` | Compact inventory: nodes, guests (name, vmid, status, node, pool, tags), storages with usage. Sized for model context, under 8k tokens, with paging for large labs |
| `proxmox://cluster/{name}/node/{node}` | Node detail: hardware, disks, ZFS pools, network |
| `proxmox://cluster/{name}/guest/{vmid}` | Guest detail with config (redacted) and snapshots |
| `proxmox://cluster/{name}/events?since=` | Recent ingested events |
| `proxmox://cluster/{name}/capacity` | Headroom per node and storage, deterministic |
| `plan://{id}` | Plan document and preview (shared core resource) |
| `job://{id}` | Job status, steps, UPIDs, outcome, verification, task log excerpt (shared core resource) |
| `proxmox://docs/permissions` | The token and permission matrix (§2.2), so the model can explain a 403 |

**Prompts** (MCP `prompts`, which appear as slash commands in clients; the content comes from the [steering pack](../steering.md)):

| Prompt | Purpose |
|---|---|
| `proxmox-health-check` | Runbook: quorum, node load, storage over 80%, ZFS health, failed backups within 24 h, pending updates, expiring tokens. Read-only, sourced summary |
| `proxmox-new-vm` | Guided `guest.plan_create`: asks for the minimum, proposes sane defaults (template, storage, size class), shows the capacity check |
| `proxmox-disk-onboarding` | New disk to pool: identify disks by serial, SMART check, recommend a layout with redundancy trade-offs, then `zfs.plan_pool` |
| `proxmox-incident` | Triage "something is down": read-only diagnostics first, hypotheses, then a plan for remediation |
| `proxmox-backup-audit` | Which guests have no recent backup, jobs failing, retention gaps |

---

## 9. Redaction specific to Proxmox

These are never logged, stored in plans, or returned to clients:
- token secrets;
- `cipassword`;
- `sshkeys` (only the fingerprints are kept);
- `args`, `hookscript`, and `cicustom` contents;
- guest-agent file-read contents;
- webhook secrets.

Config fields matching `/pass|secret|token|key/i` are masked in `guest.get`. *Implemented* in `masking.py`. Values of `args`, `hookscript`, `cicustom` and every key matching the pattern become `[MASKED]`, and `masked_keys` lists them. `sshkeys` becomes `ssh_key_fingerprints` (OpenSSH `SHA256:`), and the key comments are dropped. The pattern over-masks a few harmless keys such as `keyboard`, which is the safe direction. Task logs pass through the shared redactor before storage. A contract-kit test plants a canary secret in every one of these fields and asserts it never appears in logs, plans, MCP responses, or traces. See [observability.md](../observability.md).

**Untrusted strings.** Guest names, descriptions, tags, notes, and task logs are **untrusted content**: anyone with guest access can write to them. They are returned inside an `untrusted` envelope, so the steering pack tells the model these are data, not instructions. *Implemented:* every such field sits in an object named `untrusted`, marked `x-harness-untrusted` in the output schema. The result's `_meta` carries `homelab-harness/untrusted: true`, and the text rendering says how to read it. Node names and SMART attribute names are treated as identifiers, and the contract test records why. They never influence tier or policy. See [threat-model.md](../threat-model.md).

---

## 10. Test plan

| Layer | What | How |
|---|---|---|
| Adapter unit | Every endpoint used above: success, plus 400/401/403/500-lock/595/connect error/read timeout | **Now:** hand-written fixtures from the PVE API viewer docs (`tests/fixtures/pve-9.2/<endpoint>/<case>.json`), replayed with `respx`; an error-mapping table with a canary in the body; TLS pinning against a local server with certificates generated at test time; UPID round-trip tests. **Later:** replace the fixtures with recordings captured once from a lab node, secrets scrubbed. |
| Planner unit (pure) | Preflight and preview for every plan kind; tier floors; escalation (outside pool, harness host, HA) | Plain pytest, no I/O, fixture inventories. Golden-file previews (`previews/<kind>/<case>.txt`). Changes are reviewed in diffs. |
| Executor | Step idempotency, UPID persisted before polling, resume after a crash at each step, ambiguous-write → `uncertain`, stale plan → `cancelled` | DBOS test harness with Postgres (testcontainers). Fault injection: kill after step N, drop the connection mid-call. |
| Contract kit | The shared [SDK kit](../extending.md): schema validity, annotations present, every write tool is a `plan_*`, error mapping coverage, canary-secret redaction, untrusted envelope | **Now:** `tests/test_contract.py` subclasses `homelab_harness_sdk.testing.CapabilityContract`. It plants canaries in every §9 field, and in the response body and token for 401/403/404/409/429/500/503/timeout/connect cases, across all 18 tools. |
| Bootstrap | `hh proxmox bootstrap` output | Golden file (`tests/golden/bootstrap-home.sh`, implemented; a test also checks that the §2.4 example equals it). `hh proxmox verify` against fixture permission matrices (exact match, too broad, too narrow) |
| Live suite (nested PVE) | Create from template, snapshot, rollback, migrate (2-node nested), destroy, ZFS stripe and mirror on virtual disks, network stage and revert, firewall lockout refusal, token-scope enforcement (a provision token cannot touch a guest outside the pool) | A nested PVE 9.2 cluster in VMs, reset from a snapshot per run. Manual or scheduled, not per PR. Results recorded in `docs/verification.md`. See [testing-and-evals.md](../testing-and-evals.md). |
| Reliability mapping | Each relevant requirement in [reliability.md](../reliability.md) names its test here | Enforced by the reliability-table check |

---

## 11. Open questions

1. **Exact privilege names for 9.2.x** (`SDN.Use` path for plain Linux bridges, privileges for pool membership changes, `VM.Config.Cloudinit` vs Auditor). Resolve by running bootstrap on a nested 9.2 node and checking `/access/permissions`.
2. **node-admin default** (§2.3): option A (minted per plan) is the proposed default. Confirm it is tolerable for disk-heavy sessions, or default to B with a short TTL.
3. **Network dead-man revert** depends on the linux capability having an out-of-band path that survives the change (Tailscale on the node vs the management IP). Specify it in [linux-docker.md](linux-docker.md). Until then, `network.apply` stays **disabled by default**, behind a policy flag.
4. **`apt` upgrades via SSH** vs a future official API path. Keep it behind T3 and the linux capability for now.
5. **PBS**: read-only in v1.x through the same adapter pattern (`/api2/json` with a PBS token), or straight to v2 with restore planning?
6. **OpenTofu backend**: only if the owner wants "desired state" for the agent pool. Not needed for v1.
7. **Webhook body template helpers** (`escape`, `json`) and the matcher fields on 9.2: verify live.
8. **Multiple clusters**: inventory and tools support them. PDM integration stays out until its API stabilizes.
