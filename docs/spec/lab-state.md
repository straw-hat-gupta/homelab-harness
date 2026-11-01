# Lab state, lab documents and lab logs

> **Status: specification.** Nothing here is implemented yet. This is the core of the token-efficiency goal ([vision.md](vision.md)). Terms follow the [glossary](../../GLOSSARY.md).

## Why

An agent working on a lab spends most of its tokens finding out what the lab *is*. The harness takes that work away from the model:
- **Deterministic code** collects the facts.
- They are stored as **one typed model**.
- They are rendered into **compact documents** with a known shape and a known freshness.
- Logs are handled the same way.

The model reads, cites and acts. It doesn't explore.

## The lab state model

One typed model (pydantic in Python, Postgres tables underneath) is the single source of truth for *what the harness knows*. The live target remains the source of truth for *what is*: plans always re-check live state at preflight ([safety-model.md](safety-model.md) S5).

| Entity | Key fields (illustrative) | Sources |
|---|---|---|
| `Cluster` | name, quorum, version, nodes, HA state | `/cluster/status`, `/version` |
| `Node` | name, status, CPU, memory, uptime, kernel, PVE version, subscription, IPs | `/nodes`, `/nodes/{n}/status` |
| `Guest` (VM or LXC) | vmid, name, node, type, status, cores, memory, disks, NICs (bridge, VLAN, MAC, IPs from the guest agent), tags, pool, HA, protection, last backup, snapshots, template flag | `/cluster/resources`, `/nodes/{n}/{qemu,lxc}/{id}/config` and status |
| `Storage` | id, type, content types, shared, nodes, used and total, mount | `/storage`, `/nodes/{n}/storage` |
| `ZfsPool` | name, node, layout (vdevs), health, size and free, frag, last scrub, errors | `/nodes/{n}/disks/zfs` plus the linux capability (`zpool status -p`) |
| `Disk` | by-id path, serial, model, size, type, wear, SMART health, usage (pool, LVM, filesystem, unused) | `/nodes/{n}/disks/list`, SMART |
| `Network` | bridges, bonds, VLANs, IPs, gateway, SDN zones and vnets | `/nodes/{n}/network`, `/cluster/sdn` |
| `Firewall` | cluster, node and guest enablement, rule counts, aliases, ipsets | `/cluster/firewall/*` |
| `Backup` | jobs (schedule, targets), last result per guest, retention, PBS datastores (later) | `/cluster/backup`, task history |
| `Host` (Linux, non-PVE) | hostname, OS, kernel, services, disks, Docker presence | the linux capability |
| `Stack` (Docker Compose) | host, project, services, images by digest, health, ports | the docker capability |
| `Tunnel`, `DnsRecord`, `AccessApp` | ingress rules, hostnames, Access coverage | the cloudflare capability |
| `Service` (derived) | "Grafana at grafana.example.com runs in LXC 112 on pve1, port 3000, Access on" | joined from the rows above, plus owner annotations |
| `Annotation` | owner-written notes and roles ("pve3 is the backup node", "VLAN 20 = IoT") | entered with `hh lab note` or the UI |

Rules:
- **Every row carries `as_of` and `source`.** Readers always know how old a fact is and where it came from.
- **Change detection.** Sync computes a diff against the previous state and emits `lab.changed` events with an entity, a field and the old and new values. Events feed the UI (live updates), ntfy (for example "disk SMART went bad") and the Git mirror.
- **Target-sourced strings** (names, descriptions, notes, tags) are stored as-is but marked untrusted ([safety-model.md](safety-model.md) S7).
- **No secrets in the lab state.** Masked fields (`cipassword`, keys) are dropped at ingest, not just masked on output.

## Sync

| Trigger | What refreshes |
|---|---|
| Every 30 s | Cluster resources: guest status, node load |
| Every 5 min | Configs, storage, disks, network, firewall, backups, Docker stacks, Cloudflare |
| Every 1 h | SMART, ZFS scrub status, package updates available |
| Proxmox webhook event, or a job completing | A targeted refresh of the affected entities |
| `hh lab sync [--entity …]` | On demand |

- Sync runs as DBOS scheduled workflows, one per target and entity group, idempotent. A failed source marks only its own entities stale; it never wipes them.
- Sync is read-only and uses the `read` credential tier.
- `/readyz` reports `degraded` when any target is stale beyond twice its interval.

## Lab documents

Deterministic renderers (pure functions of the lab state, snapshot-tested) produce Markdown documents with a fixed structure, served as MCP resources, through REST, and in the UI.

| URI | Content | Budget |
|---|---|---|
| `lab://overview` | Cluster health, nodes (one line each), guest counts, storage totals, alerts, stale sources, owner annotations | ≤ 1.5k tokens |
| `lab://nodes/{node}` | Node summary, guests on it, local storage and pools, NICs and bridges, recent tasks, alerts | ≤ 2k |
| `lab://guests/{vmid}` | Config summary, disks, NICs, IPs, backups, snapshots, HA, tags, related service | ≤ 1.5k |
| `lab://storage` | Every storage and pool: layout, usage, health, what uses it, unused disks | ≤ 2k |
| `lab://network` | Bridges, VLANs, SDN, IP plan, firewall summary | ≤ 2k |
| `lab://backups` | Jobs, last result per guest, guests with no backup | ≤ 1.5k |
| `lab://services` | Derived services table: name, where it runs, URL, exposure, Access | ≤ 1.5k |
| `lab://cloudflare` | Tunnels, ingress, DNS, Access coverage gaps | ≤ 1.5k |
| `lab://hosts/{host}`, `lab://stacks/{host}/{project}` | Linux and Docker details | ≤ 1.5k |
| `lab://changes?since=…` | The change log, compact | ≤ 1k per page |

Document rules:
- Every document starts with a header line: `as_of`, its sources, and staleness warnings.
- Documents are **stable and diffable**: deterministic ordering, no timestamps inside the body, units normalized (GiB, %).
- Documents link to each other by URI, so agents navigate instead of searching.
- Budgets are enforced by the renderer. When a document would exceed its budget, it summarizes and links to a paginated detail resource (`lab://guests?node=pve1&page=2`).
- The same renderers feed `hh lab show <uri>`, and the UI's object pages show the same facts.
- **Token accounting:** every resource response records its size (bytes and estimated tokens) in metrics, so the efficiency evals and Grafana can see it.

## Git mirror (optional, recommended)

When `lab.git_mirror` is configured, a DBOS workflow commits the rendered documents to a dedicated Git repository:
- **When:** at most every 5 minutes, and only when something changed.
- **Commit messages:** generated from the change events, for example `pve2: guest 112 memory 4096→8192 MiB; storage local-zfs 71%→74%`.
- **What it gives you:** a human-readable timeline of the lab ("what changed before it broke?"), plus diffable configuration history.
- **Credential:** a deploy key scoped to that one repo, brokered by the vault ([secrets.md](secrets.md)).
- **Content:** documents only, never secrets. A CI-style check in the workflow scans every commit with the redactor's patterns before pushing.

## Lab logs

### Collection

| Source | How it's collected | Labels |
|---|---|---|
| Node journald (PVE nodes and Linux hosts) | A collector agent on each host (Grafana Alloy or the OTel Collector `journald` receiver), shipping to Loki. It's installed through a recipe during onboarding. | `host`, `unit`, `priority`, `source=journal` |
| Proxmox task logs | Sync pulls the logs of finished tasks (`/nodes/{n}/tasks/{upid}/log`) and pushes them to Loki | `node`, `task_type`, `vmid`, `upid`, `status`, `source=task` |
| Proxmox firewall log | Collector, file source | `source=firewall` |
| Docker containers | Collector (Docker logs source) on Docker hosts | `host`, `project`, `service`, `source=container` |
| The harness itself | OTLP logs (already built) | `service_name=homelab-harness` |

The logs go to the same Loki the observability stack runs ([observability.md](observability.md)), or to an existing one in the lab.

### Query tool

`logs.query(target, source, unit|task_type|service, since, until, match, level, limit)`:
- It returns **de-duplicated, trimmed** lines. Repeated lines collapse into `×N`, a long line is cut with a marker, and the total stays within a token budget (default 2k).
- Each result carries a summary header: the time range, the total lines matched, and the top repeated messages.
- Log content is untrusted ([safety-model.md](safety-model.md) S7) and is redacted for registered secrets.
- `logs.around(event_id | upid, window)` gives the context around a specific task or event.
- `logs.query` is a T0 read tool. It never runs commands on hosts.

## Proxmox and ecosystem reference docs

Agents shouldn't need to search the web for the `qm set` flags or ZFS ashift advice:
- `docs://proxmox/...`, `docs://zfs/...`, `docs://cloudflare/...`, `docs://docker/...` are curated, versioned excerpts with source links: concepts, API endpoints used by recipes, gotchas.
- They are written to be short, linked from recipes and runbooks, and checked for freshness against the target versions recorded in the lab state.
- They're kept in the repo under `steering/reference/` and built with the steering pack ([steering.md](steering.md)).

## Tests

| Area | Tests |
|---|---|
| Renderers | Snapshot tests on fixture lab states (1-node, 3-node with HA, ZFS and Ceph mixes). A budget test fails when a document exceeds its budget. A determinism test renders twice and compares. |
| Sync | Fixture-driven mapping from API responses to the model. Diff and events on changes. A failed source marks its entities stale without wiping them. Masked fields never stored. |
| Logs | Dedup, trim and budget on synthetic floods. A redaction canary. A Loki query contract tested against a test Loki container. |
| Git mirror | Commits only on change. Message generation. A canary secret refuses the push. |
