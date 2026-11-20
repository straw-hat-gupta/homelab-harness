# Lab state, memory and history

> **Status: binding target design; not implemented.** Stage 1 uses the smallest observations needed for discovery. It does not require a comprehensive inventory database, periodic sync system, centralized logs or Git mirror.

## Distinct stores and authority

| Information | Writer / authority | Handling |
|---|---|---|
| Observed cluster facts | Deterministic approved reads; live target is authoritative | Typed snapshot, source, instance/cluster identity and observation time; explicit partial/stale state |
| Owner notes/conventions | Authenticated owner | Readable versioned files; preferences, not permissions; pasted target text stays untrusted |
| Native conversation history | Official runtime | Persistent private runtime state on guest; resume through supported interface |
| Session mapping/lifecycle | Service | Instance, owner, runtime/native session ID, run state and last known outcome |
| Audit | Trusted service/tool boundary | Append-only identifiers/counts/outcomes, no raw conversation or target bodies |
| Credentials | Runtime-supported store or trusted target broker | Separate protected custody; never ordinary memory |

The file-based memory experience is a service-owned workspace of owner notes and deterministic observations. Exact serialization and application persistence are implementation decisions. Do not replicate the runtime's transcript as another source of truth. Replacing the Mac must not erase history or require rediscovery solely because the client changed.

## Observations

Start with cluster/node identity and reachability, guest placement/type/status, node CPU/memory and node/storage usage. Strip secret-bearing fields before persistence. Preserve numeric units and shared-storage identity. Never infer workload admission from raw free totals. The selected instance/cluster identity scopes every snapshot; no cross-instance reuse by alias.

An unavailable source marks only its observations unavailable/stale and retains last-known data with its timestamp. It does not report an empty healthy cluster or delete missing entities as a fact. Refresh on owner request or before answering a volatile-state question. The first stage has no blanket always-current claim or scheduled sync obligation.

## Context rendering

Render compact stable views with provenance/freshness. Enforce a byte/item/token-estimate budget, indicate truncation and offer scoped detail when needed. Label target-derived strings as data; never promote a description, log or model summary into trusted instructions. Exact size limits are decided/tested before integration, not left unbounded until later.

The runtime owns conversation compaction. On start/resume, provide supported operator instructions and relevant fresh context rather than dumping every file or transcript. Verify that instructions remain effective through native compaction; do not assume the wrapper can replace every runtime's internal system prompt.

## Recovery and privacy

Use safe atomic observation/note updates and a real tested persistence boundary. After restart, retain native IDs/history, mark incomplete runs interrupted and do not auto-repeat lost requests. Source freshness and runtime thread identity survive reconnect. Owner-controlled notes cannot silently install tools, widen access or approve actions.

Set private-history access, retention, backups and export behavior before storing real conversations. No automatic Git publication, global memory search, vector database, self-written memory or generic filesystem tool is required initially. Future changes must preserve [safety](safety-model.md) and [secrets](secrets.md).
