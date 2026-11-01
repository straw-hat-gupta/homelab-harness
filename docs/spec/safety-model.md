# Safety model

> **Status: specification.** Nothing here is implemented yet. This document is binding on all capabilities. A capability spec may make a rule stricter but never looser. Terms follow the [glossary](../../GLOSSARY.md).

## Why this exists

The harness gives an AI model operator access to real infrastructure, where one wrong call can destroy disks, lock the owner out of the network, or put a service on the public internet. The model may be wrong. It may also be manipulated by text it reads: a VM description, a log line, a note, a DNS TXT record. The safety model assumes both will happen and makes the dangerous outcomes structurally impossible, rather than relying on the model behaving well.

## Invariants

These are tested properties of the system ([reliability.md](reliability.md) maps each one to a test). They are not guidelines.

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
| S9 | **Secrets never leave the vault.** Capability tokens are encrypted at rest, never returned by any tool, never logged, and never included in previews, traces or errors. A canary-secret test covers every surface. |
| S10 | **Everything is audited.** Request, plan, preview hash, policy decision, approval (who, which channel, when), job steps, external task IDs, outcome and verification are written to an append-only log. |

## Risk tiers

| Tier | Meaning | Approval | Examples |
|---|---|---|---|
| **T0** read | No side effect | None; no plan | List guests, read SMART, tail a journal, show tunnel config |
| **T1** reversible, in scope | Fully reversible, and limited to resources the harness owns (agent pool, inbox file) | **Auto-approved** if `policy.auto_approve_t1` (default on). Owner is notified after. | Start, stop or snapshot a guest in the agent pool. Create a guest from a template in the agent pool. Add an Obsidian task. |
| **T2** recoverable change | Changes something the owner cares about. Recovery is possible but not trivial. | Owner approval (one tap) | Config change on a non-agent guest, migration, compose `up` with new images, DNS record change, firewall rule addition, note edit via PR |
| **T3** destructive or lockout | Irreversible data loss, or a risk of losing access | Owner approval **plus typed confirmation** of the target's identity (pool name, VMID plus name, disk serial suffix), using the CLI or UI. A phone tap alone is not enough. Re-preflight is mandatory. | Destroy a guest. Wipe a disk or create a ZFS pool. Snapshot rollback. Restore over an existing guest. Network apply. Firewall enable or policy change. ACL or token changes. Console or raw shell. Node reboot or upgrade. Publishing a public hostname. |

### Floors (in code; config cannot lower them)

- Anything that deletes data, or makes data unreachable, is **T3**.
- Anything that can sever the harness's or the owner's access to a target is **T3**: network, firewall, SSH config, ACLs, tokens, Tailscale ACLs.
- A raw shell or arbitrary command is **T3**, and the preview shows the exact argv.
- Any public exposure is **T3** and must include an access-control step in the same plan, or the plan is refused. See [cloudflare.md](capabilities/cloudflare.md).
- Acting on a guest **outside** the agent pool is at least **T2**.
- A plan whose step count exceeds `policy.max_steps` (default 20) is at least **T2**, so bulk changes get a human look.

### Raising tiers

Config (`policy.toml`, versioned in the deploy repo) can raise tiers, for example "anything on `pve-prod` is T3". It can also add deny rules, such as "never touch VMID 100". Deny rules are checked at plan time and again at apply time.

## Plans and previews

Every plan contains:

```
Plan
  id, hash (sha256 of canonical JSON of everything below), created_at, created_by (client id)
  kind              e.g. "proxmox.zfs.create"
  target            e.g. cluster "home", node "pve1"
  intent            short human sentence, written by the harness from the parameters (not by the model)
  parameters        validated, typed (pydantic) — exactly what will be executed
  observed          facts captured at plan time that preflight re-checks (digests, serials, record ids)
  preflight         list of checks: name, result (pass/warn/fail), evidence
  preview           structured diff + rendered text: before → after, exact API calls / argv
  risk              tier, reasons (which rules fired), floors applied
  steps             ordered executor steps with their retry class (read | idempotent | unsafe)
  rollback          what undoes this (or "irreversible"), and whether the harness can do it
  provenance        which parameters were derived from target-sourced text (see S7)
```

Rules:
- Any failed preflight check means the plan is stored as `refused` with reasons and cannot be approved. A warning is shown prominently in the preview and in the ntfy message.
- The `intent` and preview are rendered by deterministic code. The model's explanation may accompany them in the client, but the approval message shows only harness-rendered text, so the model cannot misdescribe what the owner is approving.
- Previews name things the way the owner can verify them: disk model plus serial, not `/dev/sdb`; VMID plus name plus node; zone plus record name plus old and new value.

## Approval flow

```
plan stored (T2/T3) → approval row "pending" (expires_at) → ntfy message:
   title:  "T3 · Create ZFS pool 'tank2' on pve1"
   body:   harness-rendered preview (truncated) + link to full preview (tailnet URL)
   actions: [Approve]  [Reject]          (T3: [Approve] opens CLI/UI typed-confirm, no one-tap)
owner acts → callback with single-use signed token → approval "approved" (who, channel, ts)
job starts → claims approval in same DB transaction as job creation (SELECT … FOR UPDATE)
```

- The ntfy action URLs carry a single-use, short-lived token bound to `(plan_hash, decision)`. They are reachable only over the tailnet or through Access-protected endpoints.
- Clients learn the result by polling `job.get` or reading the `job://` resource. The steering pack tells models to say "awaiting your approval" and never to claim success before the job reports its outcome.
- Rejected and expired plans are kept for audit. Re-asking creates a new plan.

## Provenance and prompt injection

The harness can't stop a client model from reading malicious text. It controls what that text can cause:
1. **Delimiting.** Tool results put target-sourced strings in fields named for what they are (`description`, `log_lines`, `note_body`). Each response carries `"untrusted": true` metadata. The steering pack teaches models to treat those fields as data.
2. **No tool selection by content.** The harness never chooses a tool or action based on target-sourced text. Only clients call tools.
3. **Provenance marking.** When a plan parameter equals or contains a string that the same session recently read from a target-sourced field, the planner marks it in `provenance`. Policy refuses T1 auto-approval for such plans, and the preview flags it. For example, a hostname copied from a log line must be confirmed by the owner. This is best effort and defense in depth. The real protection is that T2 and T3 always need the owner.
4. **Evals.** The injection suite in [testing-and-evals.md](testing-and-evals.md) plants instructions in VM descriptions, notes, journal lines, compose labels and DNS TXT records. It asserts that no T2+ job runs and that T1 auto-approval doesn't fire.

## Concurrency and locking

- One job at a time per target scope: per Proxmox node for node-level operations, per guest, per storage, per Docker host stack, per DNS zone. DBOS queues enforce this with concurrency keys.
- The harness never clears a Proxmox `lock`. A locked guest causes a preflight failure, which reports the lock type.
- Optimistic concurrency uses the target's own mechanisms where they exist: the Proxmox `digest`, the GitHub content SHA, and Cloudflare record IDs plus values.

## What the harness will not do (v1)

- Act on more than one cluster in a single plan.
- Run any operation without a preview, even for the owner through the CLI. The CLI uses the same plan path.
- Store or relay Claude or ChatGPT subscription credentials ([clients.md](clients.md)).
- Execute model-written scripts. Typed operations come first, and a raw command is T3 with its exact argv shown.
