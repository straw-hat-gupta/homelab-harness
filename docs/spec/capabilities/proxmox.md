# Proxmox discovery tools

> **Status: binding Stage 1 boundary; not implemented.** The old adapter and 18 read tools are [preserved source](../../code-reuse.md), not current capability. Exact PVE version/permissions must be verified on the owner's cluster before claiming support.

## Minimum read workflows

| Workflow | Required facts | Candidate API sources to verify |
|---|---|---|
| Cluster/node discovery | Stable cluster identity, nodes, reachability, quorum if available | Version, cluster status/resources, node list |
| VM/LXC inventory | VMID, type, name, node, running state; partial-node errors | Cluster resources or per-node guest lists |
| Node resources | Physical/logical CPU information where reported, utilization and memory total/used/free | Node status |
| Node storage | Storage identity, node availability, shared/local flag, total/used/free and content type | Storage configuration and per-node storage status |

These are task contracts, not a mandate for one tool per endpoint or a full SDK. Choose a small typed registry with bounded filters/results and explicit source/time. Reuse the archived adapter only after checking actual target shapes, dependencies and failure behavior.

## Credential and trust requirements

Use a dedicated read-only API token and verified HTTPS trust (trusted CA or owner-confirmed certificate pin). Never use root passwords, disable verification, accept changed identity silently or create provision/node-admin tokens during read-only setup. Public trust does not prove the intended cluster; bind instance registration to target identity too.

Determine exact privileges from the owner's supported PVE version and the tool subset. Verify no missing/excess rights and distinguish authentication rejection from permission denial. If a read needs more authority than agreed, report the limit rather than escalate. Do not promise that a built-in role covers every future diagnostic endpoint.

## Adapter/tool contract

Validate typed inputs before I/O, allow only registered targets, set connection/request deadlines and map failures to safe errors without raw provider bodies. Reads never mutate targets, refresh packages, generate tokens or clear locks. The broker uses credentials without returning them to the runtime.

Return units, source, observation time, partial failures and truncation metadata. Drop/mask cloud-init passwords, private keys, tokens, arbitrary launch arguments, hook/custom script contents and other secret-bearing config. Avoid full guest configuration if the initial questions do not require it. Target names/descriptions remain labelled untrusted.

Do not double-count shared storage, label unavailable sources empty, equate logical CPUs with allocatable capacity or infer VM placement promises from free memory alone. Config identity, HA/locks, reservations and placement policy are separate later work.

## Acceptance

Fixture-test success and malformed data, 401/403/404/conflict/rate-limit/5xx, TLS mismatch, connection/read timeout, partial-node failure and output budgets. Canary tests cover responses, errors, logs, audit and snapshots. Record scrubbed live shapes only during explicit owner testing; do not commit real credentials or private cluster details. Compare actual discovery results with Proxmox in 1B and the model's answers in 1D.

Writes, task execution/polling, node routing/failover guarantees, broad storage/network operations, consoles and per-node collectors are excluded. A future write must satisfy [safety S1–S10](../safety-model.md); no raw fallback is permitted when a read or future recipe is missing.
