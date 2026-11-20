# Reliability requirements

> **Status: requirement ledger; every application requirement is unimplemented on this documentation-only branch.** Evidence from the retired application is preserved in the snapshot and is not current coverage. R-01–R-46 retain their identity/intent; store/command assumptions are narrowed to the newly selected boundary. R-47 onward cover the managed-runtime design.

A requirement becomes applicable when its behavior is enabled. Deferral does not permit an unsafe substitute. Fill evidence with an actual test/acceptance reference only when implemented; no existing test pointer is a claim that removed code remains active. See [testing/evals](testing-and-evals.md) and [Stage 1](../stage-1.md).

| ID | Required behavior | Applicability | Current evidence |
|---|---|---|---|
| R-01 | Application-owned state persists through the real chosen store; native runtime history is verified through its supported interface. Do not mock either persistence boundary. | Stage 1, before the affected behavior is enabled | Not implemented |
| R-02 | Unsafe external writes are never retried after an ambiguous outcome. The job ends `uncertain`. | When relevant write/automation/mode is introduced | Not implemented |
| R-03 | A step deadline bounds the external work itself (the request timeout comes from the remaining budget). A reported timeout means the call was abandoned, not that it is still running in a thread. | Stage 1, before the affected behavior is enabled | Not implemented |
| R-04 | Previewing has no side effects. `plan_*` and read tools never mutate targets, never spend money, and never persist anything except the plan row. | Stage 1, before the affected behavior is enabled | Not implemented |
| R-05 | An approval is claimed once, atomically with job creation. Concurrent claims result in one job. | When relevant write/automation/mode is introduced | Not implemented |
| R-06 | All target mutations, from CLI/runtime/schedules/events or any future interface, share the stored-plan/authorized execution boundary. Reads share deterministic tool authorization. | Stage 1, before the affected behavior is enabled | Not implemented |
| R-07 | The approval shows resolved parameters (the harness-rendered preview), never model prose. | When relevant write/automation/mode is introduced | Not implemented |
| R-08 | Approval is a deterministic owner action bound to a plan hash. No model classification decides it. | When relevant write/automation/mode is introduced | Not implemented |
| R-09 | Plans are fully validated (typed parameters, references and preflight) before any step runs. An invalid plan has zero side effects. | When relevant write/automation/mode is introduced | Not implemented |
| R-10 | Apply-time preflight detects drift. A stale plan is cancelled, not partly applied. | When relevant write/automation/mode is introduced | Not implemented |
| R-11 | Durable jobs resume after a crash at any step without duplicating a completed external call. | When relevant write/automation/mode is introduced | Not implemented |
| R-12 | Scheduled and event-triggered work is claimed exactly once and recovered if dispatch was interrupted. | When relevant write/automation/mode is introduced | Not implemented |
| R-13 | Sequences (audit event order, job steps) are unique per parent, enforced by constraint. | Stage 1, before the affected behavior is enabled | Not implemented |
| R-14 | A transient target failure never permanently disables a credential. Only a definitive rejection (401 with invalid token, revoked) marks it unusable, and the owner is notified. | Stage 1, before the affected behavior is enabled | Not implemented |
| R-15 | Credential use is serialized where the target requires it (ticket refresh). | When relevant write/automation/mode is introduced | Not implemented |
| R-16 | No secrets or target content in logs, traces, errors or audit summaries (canary test per capability). | Stage 1, before the affected behavior is enabled | Not implemented |
| R-17 | Every tool declares the least-privilege credential tier it needs. Bootstrap verifies each token has exactly the expected privileges (none missing, none extra). | Stage 1, before the affected behavior is enabled | Not implemented |
| R-18 | All inputs are validated at the boundary (pydantic). Bad input returns a 4xx or MCP error, never a 500. | Stage 1, before the affected behavior is enabled | Not implemented |
| R-19 | List operations paginate correctly, with cursors scoped to their query and target. | Relevant Stage 1 subset; broader features deferred | Not implemented |
| R-20 | Parsers are pure and fixture-tested with real-world shapes (Proxmox API responses, Tasks lines, compose files, journal output). | Relevant Stage 1 subset; broader features deferred | Not implemented |
| R-21 | Times are aware UTC internally, converted at the edges with `zoneinfo`. Reminders are tested across DST in both directions. | Relevant Stage 1 subset; broader features deferred | Not implemented |
| R-22 | A capability's business rules have one owner (its planner and executor). No duplicate implementations across entry points. | Relevant Stage 1 subset; broader features deferred | Not implemented |
| R-23 | A clean install reaches the accepted increment by following its current instructions; do not require an unimplemented doctor command. | Stage 1, before the affected behavior is enabled | Not implemented |
| R-24 | Settings are read in one place (pydantic-settings), with no stray `os.getenv`. Tests don't load a developer `.env`. | Stage 1, before the affected behavior is enabled | Not implemented |
| R-25 | The KEK rotates by rewrapping DEKs (`hh vault rotate-kek`), and secrets rotate by version. Startup fails clearly if the KEK provider is missing or wrong. There is no plaintext fallback. | Stage 1, before the affected behavior is enabled | Not implemented |
| R-26 | Locked dependencies have no known high or critical CVEs at release (pip-audit in CI). | Stage 1, before the affected behavior is enabled | Not implemented |
| R-27 | Disk identity: destructive disk operations target `/dev/disk/by-id` paths matched to recorded serials, and refuse non-empty disks. | When relevant write/automation/mode is introduced | Not implemented |
| R-28 | Lockout protection: network, firewall and ACL plans fail preflight if they would cut the harness's or owner's access, and network apply auto-reverts unless confirmed. | When relevant write/automation/mode is introduced | Not implemented |
| R-29 | Proxmox async tasks are tracked by UPID to a terminal status. The job outcome reflects `exitstatus`, and the task log excerpt is stored. | When relevant write/automation/mode is introduced | Not implemented |
| R-30 | Public exposure is impossible without an access policy in the same plan. | When relevant write/automation/mode is introduced | Not implemented |
| R-31 | Per-scope concurrency: no two jobs mutate the same node, guest, storage, stack or zone at once. | When relevant write/automation/mode is introduced | Not implemented |
| R-32 | Prompt-injection resilience: planted instructions in target text never cause a T2+ job, or T1 auto-approval, in the eval suite. | Stage 1, before the affected behavior is enabled | Not implemented |
| R-33 | Inventory reads report `as_of`. Plans never rely on inventory alone (live preflight). | Stage 1, before the affected behavior is enabled | Not implemented |
| R-34 | No MCP tool, resource, prompt or error returns a secret value, length or hash. A schema-level test walks every tool's output type. | Stage 1, before the affected behavior is enabled | Not implemented |
| R-35 | Each secret use is checked against a grant (client, mode, scope, expiry) and audited. A use without a matching grant is refused. | Relevant Stage 1 subset; broader features deferred | Not implemented |
| R-36 | `ssh-sign` refuses to sign for a destination host key outside the grant's hosts. `http-inject` refuses upstreams, methods or paths outside its route. | When relevant write/automation/mode is introduced | Not implemented |
| R-37 | Secret intake never carries the value through MCP. A request produces URL elicitation or a link, and the intake page requires an owner session. | When relevant write/automation/mode is introduced | Not implemented |
| R-38 | Lab documents are deterministic (the same state renders byte-identical output) and stay within their token budgets. | Stage 1, before the affected behavior is enabled | Not implemented |
| R-39 | A failed sync source marks only its own entities stale. It never deletes or blanks them, and readiness reports `degraded`. | Relevant Stage 1 subset; broader features deferred | Not implemented |
| R-40 | Secret-bearing fields (`cipassword`, keys, tokens) are dropped at ingest and never stored in the lab state or the Git mirror. | Stage 1, before the affected behavior is enabled | Not implemented |
| R-41 | `logs.query` output is de-duplicated, trimmed, within budget, redacted, and marked untrusted. | Relevant Stage 1 subset; broader features deferred | Not implemented |
| R-42 | Recipes take typed inputs and entity references (no free-text identifiers), declare a tier at or above the floors, have verify and rollback, and record `recipe@version` on every plan and job. | When relevant write/automation/mode is introduced | Not implemented |
| R-43 | Every failed job carries a failure class: agent, recipe, target or uncertain. | When relevant write/automation/mode is introduced | Not implemented |
| R-44 | Discovery is read-only; any identity/bootstrap effect is a separate owner-reviewed change. Re-running setup does not overwrite keys, identities or existing configuration. | Stage 1, before the affected behavior is enabled | Not implemented |
| R-45 | No duplicate/orphaned active tools or shared parts; search/review existing components before adding. A full searchable catalog is a later implementation, not a first-tool prerequisite. | Relevant Stage 1 subset; broader features deferred | Not implemented |
| R-46 | Context/output budgets are explicit and regression-tested from the first conversation. Token savings are measured rather than asserted; any future allowed regression threshold is recorded. | Stage 1, before the affected behavior is enabled | Not implemented |
| R-47 | Launch the real unmodified CLI through supported auth/control; no wrapper credential-cache reads or custom inference loop. | Stage 1 | Not implemented |
| R-48 | Bind saved connections, sessions, observations and credentials to verified instance/cluster identity; aliases cannot cross-route state. | Stage 1 | Not implemented |
| R-49 | Runtime native tools cannot read target/provider credentials or bypass the read-only domain/owner boundary; prove effective isolation before target access. | Stage 1 | Not implemented |
| R-50 | Run/tool/call/context/output limits are enforced; cancellation bounds child/tool work and reports incomplete termination honestly. | Stage 1 | Not implemented |
| R-51 | Reconnect and restart preserve native history/session mapping, mark interrupted runs and never silently replay lost requests. | Stage 1 | Not implemented |
| R-52 | Owner-managed notes, deterministic observations, native transcripts, secrets and audit have separate writers, authority, freshness and retention. | Stage 1 | Not implemented |
| R-53 | Actual model/runtime fixture evaluations and explicit owner-lab acceptance gate each increment; scripted transcripts and historical test counts are insufficient. | Stage 1 | Not implemented |

## Safety coverage

S1 maps to R-04/R-06; S2 to R-08/R-49; S3 to R-05; S4 to R-07/R-09; S5 to R-10; S6 to R-02/R-11; S7 to R-32/R-52; S8 to R-17/R-49; S9 to R-16/R-25/R-34–R-37/R-49; S10 to R-13. These mappings do not replace direct invariant tests when code returns.

## Historical sources

The [preserved reliability ledger](https://github.com/straw-hat-gupta/homelab-harness/blob/a97f2aacd611f0a6b666f336fda57fad88c27080/docs/spec/reliability.md) retains old test pointers and implementation status. General lessons from the [v0 audit](../archive/v0/audit-2026-10-30.md) and [cross-check](../archive/v0/audit-cross-check-2026-10-31.md) remain relevant. Gmail, calendar and personal-assistant features are not reintroduced by keeping their failure lessons.
