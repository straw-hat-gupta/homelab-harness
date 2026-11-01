# Reliability requirements

> **Status: specification.** Every row is a requirement with a named test. The "Test" column is filled in as the code lands. A release can't ship while a v1 row has an empty Test cell. This table becomes the README's reliability section.

These requirements come from three sources:
1. The safety invariants in [safety-model.md](safety-model.md) (S1–S10).
2. The failure modes found in v0 by the [audit](../archive/v0/audit-2026-10-30.md) and its [cross-check](../archive/v0/audit-cross-check-2026-10-31.md), recorded so the rewrite provably avoids them.
3. Infrastructure-specific failure modes.

## Requirements

| ID | Requirement | Origin | Test |
|---|---|---|---|
| R-01 | Persistence works in the real async path. Tests use the real database for conversation, plan and approval state; they never mock the store boundary. | v0 #1, #20 | |
| R-02 | Unsafe external writes are never retried after an ambiguous outcome. The job ends `uncertain`. | v0 #2, x-check 4 | |
| R-03 | A step deadline bounds the external work itself (the request timeout comes from the remaining budget). A reported timeout means the call was abandoned, not that it is still running in a thread. | v0 #2 | |
| R-04 | Previewing has no side effects. `plan_*` and read tools never mutate targets, never spend money, and never persist anything except the plan row. | v0 #3, x-check 1 | |
| R-05 | An approval is claimed once, atomically with job creation. Concurrent claims result in one job. | v0 #3 | |
| R-06 | Policy is enforced at the single execution boundary. CLI, schedules, events and MCP all reach targets only through jobs. | v0 #4 | |
| R-07 | The approval shows resolved parameters (the harness-rendered preview), never model prose. | v0 #4, x-check 3 | |
| R-08 | Approval is a deterministic owner action bound to a plan hash. No model classification decides it. | x-check 3 | |
| R-09 | Plans are fully validated (typed parameters, references and preflight) before any step runs. An invalid plan has zero side effects. | v0 #6, x-check 2 | |
| R-10 | Apply-time preflight detects drift. A stale plan is cancelled, not partly applied. | new (infra) | |
| R-11 | Durable jobs resume after a crash at any step without duplicating a completed external call. | v0 #7 | Partial: `test_dbos.py::test_rerunning_a_workflow_id_returns_the_recorded_result_without_reexecuting`, `::test_resuming_after_a_step_reuses_completed_steps` (DBOS replay of recorded steps; the job engine and crash tests come in Stage 2) |
| R-12 | Scheduled and event-triggered work is claimed exactly once and recovered if dispatch was interrupted. | v0 #7 | |
| R-13 | Sequences (audit event order, job steps) are unique per parent, enforced by constraint. | v0 #8 | Audit: `test_audit.py::test_seq_is_unique_and_cannot_be_chosen_by_the_caller` (`GENERATED ALWAYS` identity plus `uq_audit_events_seq`). Job steps: Stage 2 |
| R-14 | A transient target failure never permanently disables a credential. Only a definitive rejection (401 with invalid token, revoked) marks it unusable, and the owner is notified. | v0 #9 | |
| R-15 | Credential use is serialized where the target requires it (ticket refresh). | v0 #9 | |
| R-16 | No secrets or target content in logs, traces, errors or audit summaries (canary test per capability). | v0 #10, x-check 5, 6 | |
| R-17 | Every tool declares the least-privilege credential tier it needs. Bootstrap verifies each token has exactly the expected privileges (none missing, none extra). | v0 #11 | |
| R-18 | All inputs are validated at the boundary (pydantic). Bad input returns a 4xx or MCP error, never a 500. | v0 #12 | |
| R-19 | List operations paginate correctly, with cursors scoped to their query and target. | v0 #13 | |
| R-20 | Parsers are pure and fixture-tested with real-world shapes (Proxmox API responses, Tasks lines, compose files, journal output). | v0 #14 | |
| R-21 | Times are aware UTC internally, converted at the edges with `zoneinfo`. Reminders are tested across DST in both directions. | v0 #15 | |
| R-22 | A capability's business rules have one owner (its planner and executor). No duplicate implementations across entry points. | v0 #17 | |
| R-23 | A clean install reaches a healthy stack (`docker compose up`, then `hh doctor` green) by following the docs alone. | v0 #18, x-check 9 | |
| R-24 | Settings are read in one place (pydantic-settings), with no stray `os.getenv`. Tests don't load a developer `.env`. | x-check 8 | |
| R-25 | The KEK rotates by rewrapping DEKs (`hh vault rotate-kek`), and secrets rotate by version. Startup fails clearly if the KEK provider is missing or wrong. There is no plaintext fallback. | x-check 7 | |
| R-26 | Locked dependencies have no known high or critical CVEs at release (pip-audit in CI). | x-check CVEs | |
| R-27 | Disk identity: destructive disk operations target `/dev/disk/by-id` paths matched to recorded serials, and refuse non-empty disks. | new (infra) | |
| R-28 | Lockout protection: network, firewall and ACL plans fail preflight if they would cut the harness's or owner's access, and network apply auto-reverts unless confirmed. | new (infra) | |
| R-29 | Proxmox async tasks are tracked by UPID to a terminal status. The job outcome reflects `exitstatus`, and the task log excerpt is stored. | new (infra) | |
| R-30 | Public exposure is impossible without an access policy in the same plan. | new (infra) | |
| R-31 | Per-scope concurrency: no two jobs mutate the same node, guest, storage, stack or zone at once. | new (infra) | |
| R-32 | Prompt-injection resilience: planted instructions in target text never cause a T2+ job, or T1 auto-approval, in the eval suite. | new (AI) | |
| R-33 | Inventory reads report `as_of`. Plans never rely on inventory alone (live preflight). | new (infra) | |
| R-34 | No MCP tool, resource, prompt or error returns a secret value, length or hash. A schema-level test walks every tool's output type. | new (secrets) | |
| R-35 | Each secret use is checked against a grant (client, mode, scope, expiry) and audited. A use without a matching grant is refused. | new (secrets) | |
| R-36 | `ssh-sign` refuses to sign for a destination host key outside the grant's hosts. `http-inject` refuses upstreams, methods or paths outside its route. | new (secrets) | |
| R-37 | Secret intake never carries the value through MCP. A request produces URL elicitation or a link, and the intake page requires an owner session. | new (secrets) | |

Safety invariants S1–S10 are tested directly. Most also map to a row above: S1→R-04/R-06, S2→R-08, S3→R-05, S4→R-07, S5→R-10, S6→R-02, S7→R-32, S8→R-17, S9→R-16, S10→R-13.

## v0 findings with no counterpart

Gmail MIME parsing (#14 specifics), Gmail and Calendar pagination (#13 specifics), contact uploads (#18 specifics) and the dead-code inventory (#19) relate to features that are not being rebuilt. Their general lessons are kept as R-19 and R-20.
