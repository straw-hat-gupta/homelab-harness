# Glossary

Terms used by the active design. Historical documents may use older meanings.

| Term | Meaning |
|---|---|
| Harness | The whole Homelab Harness product around managed agent runtimes: connections, workspace, context, tools, policy and later supervision. |
| Harness instance | One cluster-side service installation managing one Proxmox cluster. Saved Mac connections select instances, not arbitrary target endpoints. |
| Service guest | The dedicated VM/container hosting the instance and its persistent workspace. |
| Client | Our thin Mac CLI, or a future GUI, connecting to an instance. It does not run the agent or hold authoritative lab memory. |
| Runtime | The real, unmodified `claude` or `codex` program. It owns model/tool iteration, provider authentication and native conversation history/compaction. |
| Model | Inference producing answers and proposed tool calls. A raw model endpoint is not a complete runtime. |
| Provider | Where inference is served: vendor cloud, local model server or a VPS endpoint. Runtime/provider compatibility must be tested. |
| Agent | A runtime session configured with a model, instructions, workspace and allowed tools. |
| Session | A conversation identified by the instance and the runtime's native session/thread identifier. |
| Run | One bounded response to an owner's request, possibly involving several model/tool turns. Stage 1 permits one active run per instance. |
| Owner | The single human who configures the instance, supplies credentials and authorizes changes. |
| Owner channel | Authenticated configuration/approval input unavailable to the model, even when displayed in the same terminal as chat. |
| Tool | A typed, authorized domain operation exposed to the runtime, initially read-only through MCP. |
| Adapter | Typed target communication with timeouts and safe errors; no policy or storage ownership. |
| Target | The registered cluster, node, guest or storage being inspected or operated on. |
| Discovery | Deterministic read-only collection of facts through approved tools; not model-generated exploration commands. |
| Lab state | What the harness has observed, with source, observation time and explicit freshness. The live target remains authoritative. |
| Lab document | A bounded, deterministic view of observed facts, with links to detail when needed. URI syntax and storage schema are not committed yet. |
| Memory | Service-owned owner notes and observed facts, separate from runtime conversation history, audit and credential storage. |
| Lab profile | Owner-approved conventions and annotations. It cannot grant authority or replace fresh facts. |
| Plan | An immutable typed proposal for a target change, including resolved inputs, preflight evidence, preview, tier, steps, rollback note and content hash. |
| Preview | Deterministic rendering of the exact proposed effect; model prose cannot replace it. |
| Preflight | Live validation at plan time and again before apply. |
| Policy / tier | Deterministic authorization, including non-lowerable risk floors. T0 reads; T1 reversible/in scope; T2 meaningful recoverable change; T3 destructive/lockout/public exposure. |
| Approval | Owner decision bound to one plan hash, expiring and claimed at most once. Never inferred from model-classified chat. |
| Job / apply | Durable execution of an approved stored plan. The engine is a later decision, not the conversation runtime. |
| Outcome | Verified success, definite failure, cancellation/interruption, or uncertain effect requiring investigation. |
| UPID | Proxmox task identifier; later write jobs persist it before polling rather than resubmitting a write. |
| Secret / handle | Protected credential and its non-secret reference, such as `secret://pve-read`. Only the handle may reach the agent. |
| Grant | Owner authorization for a principal to use a secret in a mode/scope until expiry. It does not reveal the value. |
| Broker | Trusted tool-side execution which uses a credential without giving it to the agent. |
| KEK / DEK | Encryption key held outside credential storage, and per-secret-version data key wrapped by it. |
| Audit | Append-only record of identities, operations, policy and outcomes. No raw prompts, target bodies or secret values. |
| Recipe / step | Later reusable typed operation and its shared execution units. Not a requirement to build a recipe framework for Stage 1. |
| Widget / template | Later GUI configuration combining data and a generic renderer. This principle does not select a frontend framework. |
| Role / job supervision | Later bounded authority/instructions and management of multiple agents or background work. Excluded from Stage 1. |
| Acceptance gate | Recorded owner testing of an increment on the lab, distinct from automated fixture tests. |
