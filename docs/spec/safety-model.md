# Safety model

> **Status: binding requirements, not an implementation claim.** Stage 1 has no target writes. These requirements apply to all entry points and future features; they may only be made stricter. [Reliability](reliability.md) identifies the evidence required before shipping.

## Preserved invariants

S1–S10 are retained verbatim from the previous safety contract. References to DBOS, ntfy and particular target examples in those rows describe the historical design, not mandatory infrastructure for the restart. Their safety meaning applies to any selected engine/channel. No current implementation or contract kit is claimed to exist.

| ID | Invariant |
|---|---|
| S1 | **No write without a plan.** The only code path that mutates a target is a job applying a stored plan. Read tools and `plan_*` tools have no external side effects. The contract test kit enforces this for every capability: tools are classified, and adapters' write methods may be called only from executors. |
| S2 | **The model cannot approve.** No MCP tool, resource or prompt can approve, claim or modify an approval. Approvals arrive only through authenticated owner channels: the CLI, the ntfy action callback, and later the web UI. |
| S3 | **An approval binds to exactly one plan hash, is claimed at most once, and expires.** Default expiry is 15 min for T3 and 60 min for T2. A second claim, a claim after expiry, or a claim against a different hash is rejected and audited. |
| S4 | **Tiers come from policy, not the model.** The planner and policy assign the tier from the plan's kind and its live facts. Model-supplied text never lowers it. Code-level **floors** cannot be lowered by config. |
| S5 | **Preflight runs at plan time and again at apply time.** If live state has drifted from what the plan recorded (config digest, disk serials, pool membership, record IDs), the job ends as `cancelled: stale plan`, and a new plan is required. |
| S6 | **Ambiguous effects are never retried blindly.** A step whose outcome is unknown (read timeout after send, connection lost after the request) ends the job as `uncertain`, notifies the owner, and is not replayed by DBOS recovery. Retries happen only for steps declared `read` or `idempotent`. |
| S7 | **Target-sourced text is data.** Text that comes from a target (names, descriptions, notes, logs, command output, DNS records, commit messages) is returned to clients inside clearly delimited, labelled fields and never interpreted as instructions by the harness. A plan whose arguments came from such text gets no tier reduction (see "Provenance"). |
| S8 | **Least privilege is enforced by the target.** Each capability tier has its own credential, scoped by the target's own access control (Proxmox ACLs and pools, Cloudflare token scopes, sudoers, a fine-grained GitHub PAT). A bug in the harness's policy must still be stopped by the target. |
| S9 | **Secrets never leave the vault.** Capability tokens are encrypted at rest, never returned by any tool, never logged, and never included in previews, traces or errors. A canary-secret test covers every surface. Agents use secrets only by handle, through grants, in the brokered modes defined in [secrets.md](secrets.md). No MCP surface returns a value. |
| S10 | **Everything is audited.** Request, plan, preview hash, policy decision, approval (who, which channel, when), job steps, external task IDs, outcome and verification are written to an append-only log. |

## Managed runtimes and Stage 1

- The model cannot approve through **any** runtime tool or interface. S2 is not limited to MCP. Owner configuration and future approvals are separate authorization paths, even if shown in the same terminal as chat.
- Only a small target-allowlisted read registry is exposed. No target writes, raw shell, generic HTTP, arbitrary filesystem or tool-installation escape hatch is enabled.
- Runtime-native tools must not read broker/provider credentials, modify trusted facts/instructions, reach owner-only APIs or bypass target policy. Supported restrictions and process/filesystem/network isolation must be demonstrated before a real target credential is supplied. A prompt or a read-only label is not enforcement.
- The official runtime may use its own protected subscription login through its supported authentication code. The wrapper does not extract, store in its vault, relay or call model endpoints with those credentials. Model-directed tools cannot read them.
- Each call/run has a deadline and output/call/context limits. Cancellation must propagate to children/tools, and external reads remain bounded independently. An interrupted run is recorded; it is not silently replayed or called successful.
- Target text and persisted observations cannot become trusted instructions or add authority. Owner notes can describe preferences but cannot create grants or approve a plan.
- Audit is append-only and fail-closed. If the operation cannot be recorded, its result is refused. Native transcripts are separate private data, not audit/log payloads.

## Risk tiers and floors for future writes

| Tier | Meaning | Minimum approval |
|---|---|---|
| T0 | No target side effect | Authorized read; no plan |
| T1 | Fully reversible and inside harness-owned scope | Owner approval initially; automatic approval disabled by default |
| T2 | Meaningful recoverable change | Authenticated owner approval |
| T3 | Destructive, lockout or public exposure risk | Owner approval plus typed target identity confirmation, with apply-time re-preflight |

Floors cannot be lowered by configuration or model text. Deletion/unreachable data, access-path changes, arbitrary commands, console access, node reboot/upgrade and public exposure are T3. Public exposure must include access control in the same plan or be refused. Work outside a harness-owned scope is at least T2. A plan over the configured step limit (historically 20) is at least T2. A missing limit/policy is not permission to proceed.

Policy may raise tiers and add deny rules. Deny rules apply at planning and execution. Future automatic T1 approval, if explicitly enabled, still requires a plan, durable job, audit and provenance checks; nothing in Stage 1 enables it.

## Plans, approval and execution

Before any target mutation, store an immutable plan with typed resolved parameters, target/instance identity, current facts/digests, preflight evidence, deterministic intent/preview, tier and rule reasons, ordered steps with retry classes, rollback limitations, provenance, creator, timestamp and canonical content hash. A failed preflight stores a refusal and cannot be approved.

The preview shows verifiable identities (VMID/name/node, disk serial, storage ID), before/after effects, exact API calls or argv and irreversible consequences. Model prose cannot substitute for it. An approval binds to exactly one hash, expires (T3 15 minutes and T2 60 minutes by default), and is atomically claimed once with execution creation. Reject mismatch, expiry, replay and concurrent duplicate claims, and audit them. An owner typing yes into chat is not an approval token or an LLM-classified approval.

Execute only through the approved plan's durable job. Re-preflight live state; drift cancels execution and needs a new plan. Persist external task identity before polling. Verify postconditions before success. An external effect with unknown outcome ends uncertain and is never blindly repeated, including recovery after a crash. A verification mismatch is not success. Every sub-step must be covered by the same resolved preview/approval; no hidden follow-on writes.

One mutating job per target scope. Never clear Proxmox locks as a workaround. Use target concurrency controls (such as config digests) and identity checks; an execution engine's retry semantics do not make arbitrary target calls idempotent.

## Injection and provenance

Clearly label target-derived descriptions, names, tags, logs and stored observations as untrusted. The harness must not interpret them as instructions for actions, recipients, targets or permissions. An operator request can refer to a discovered entity only through typed, authorized reference resolution.

Track target-derived plan parameters where possible. Best-effort provenance matching is defense in depth, not proof of model intent. It cannot lower a tier, and it blocks automatic T1 approval for such plans. Owner approval, target ACLs and executor validation remain the real authorization boundaries. [Injection evals](testing-and-evals.md) must test actual runtime/model behavior, not just scripted transcripts.

## Explicit exclusions

No cross-cluster plan, approval surface accessible to the model, unpreviewed mutation, subscription credential proxy or execution of unreviewed model-written scripts. Future extension drafting is separate from human-reviewed testing/installation; it cannot promote itself or bypass the same typed execution policy. [Secrets](secrets.md) defines the complementary binding protections.
