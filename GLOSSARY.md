# Glossary

The project's vocabulary. Use these terms, in this sense, in code, docs, issues and tests. When a concept you need is missing, add it here in the same PR.

| Term | Meaning | Avoid |
|---|---|---|
| **Harness** | The whole system: the control plane, the MCP server, the steering pack and the interfaces. | "agent", "bot" |
| **Control plane** | The Python service that owns inventory, plans, approvals, jobs, audit, credentials and policy. | "backend", "server" (too vague) |
| **Client** | An AI application connected to the harness over MCP: claude.ai, Claude Desktop, Claude Code, ChatGPT, Codex. The client runs the model; the harness runs no model. | "LLM" when you mean the app |
| **Owner** | The single human who operates the harness and approves plans. | "user" (ambiguous with Proxmox users) |
| **Capability** | A package that adds a domain to the harness, such as `proxmox`, `cloudflare`, `docker`, `linux` or `obsidian`. It contributes a typed adapter, read tools, planners, executors, resources, steering and contract tests. | "plugin", "integration" |
| **Adapter** | The part of a capability that talks to an external system: typed calls, timeouts, and error mapping to shared exceptions. It holds no policy. | "client wrapper" |
| **Target** | A system the harness manages: a Proxmox cluster or node, a Linux host, a Docker host, a Cloudflare account, a vault repo. | "remote", "host" (unless it is a Linux host) |
| **Inventory** | The control plane's cached, typed view of the targets, refreshed from the source of truth. It is read-optimized. The target is always authoritative at apply time. | "state" |
| **Read tool** | An MCP tool with no side effects. It runs immediately. | — |
| **Plan** | An immutable, typed proposal for one change. It contains the intent, the target, preflight results, a preview (diff), a risk tier, the steps, a rollback note and a content hash. Created by a `*.plan_*` tool. | "action", "proposal" |
| **Preview** | The human-readable part of a plan: what changes, before and after, and the exact commands or API calls. | "summary" |
| **Preflight** | Deterministic checks run when the plan is created and again at apply time, for example "disk has no partitions" or "config digest unchanged". | "validation" (too generic) |
| **Risk tier** | T0 read, T1 reversible and in scope, T2 recoverable change, T3 destructive or lockout risk. Assigned by policy, never by the model. See [safety-model.md](docs/spec/safety-model.md). | "severity" |
| **Policy** | Deterministic rules mapping a plan to a risk tier and an approval requirement. Defined in versioned config with code-level floors that config cannot lower. | — |
| **Approval** | The owner's out-of-band decision on one plan hash: approve, reject or expired. It is claimed exactly once. | "confirmation" |
| **Apply** | Executing an approved plan as a durable job. | "run", "execute" (in user-facing text) |
| **Job** | A durable (DBOS) workflow that applies a plan. It records steps, external task IDs (UPIDs), outcome and verification. | "task" (reserved for owner to-dos) |
| **UPID** | Proxmox's unique task identifier, returned by asynchronous API calls. Jobs persist and poll it. | — |
| **Outcome** | The terminal result of a job: `succeeded`, `failed` (definitely did not take effect), `uncertain` (may have taken effect; needs a human), `rolled_back`, `cancelled`. | — |
| **Verification** | The read performed after apply, confirming the target reached the planned state. | — |
| **Agent pool** | A Proxmox resource pool that holds guests created by the harness. Scoped tokens act only inside it. | — |
| **Secret** | A credential held in the harness vault (an SSH key, password, token, file or key/value bundle), encrypted at rest and referenced by handle. See [secrets.md](docs/spec/secrets.md). | "key" (ambiguous with encryption keys) |
| **Handle** | A secret's reference, `secret://<name>`. This is all an agent ever sees. | "secret ID" |
| **Grant** | The owner's permission for one client to use one secret in one mode, within a scope, with an approval rule and an expiry. | "permission", "share" |
| **Use mode** | How a granted secret is used: `broker`, `ssh-sign`, `http-inject`, `file-mount`, `env` (exposing), or `reveal` (owner only). | — |
| **KEK / DEK** | The key-encryption key (held outside the DB) and the per-secret data-encryption key it wraps. | "master key" |
| **Capability token** | A privilege-separated Proxmox API token, or a scoped token for another system, held for one capability and risk level. | "API key" |
| **Steering pack** | Versioned prompts, skills and runbooks that shape how clients behave. Distributed as Agent Skills, MCP prompts and resources, and AGENTS.md. | "system prompt" (only one part of it) |
| **Runbook** | A steering document for one kind of work. It follows the order trigger, read-only diagnostics, hypotheses, plan, verify, rollback. | "playbook" (that word is Ansible's) |
| **Task** | An owner to-do item, stored as an Obsidian Tasks line in the vault repo. | using it for Proxmox tasks (say UPID or job) |
| **Event** | Something reported by a target, such as a Proxmox notification webhook or a failed backup, and ingested by the control plane. | "alert" (an alert is an event the policy chooses to notify on) |
| **Usage** | Token, cost and rate-limit consumption reported by connected clients through their telemetry. | "billing" |
