# Testing, evaluations and owner acceptance

> **Status: requirements only.** There is no executable suite in the active documentation checkpoint. Historical test counts belong to the preserved application. [Reliability](reliability.md) is a requirement ledger, not evidence that code exists.

## Three kinds of evidence

| Evidence | Purpose | Environment |
|---|---|---|
| Automated tests | Deterministic validation, adapters, policy, bounds, persistence and lifecycle behavior | Fake provider/target network boundaries; real selected local persistence; never the owner's lab/account by default |
| Live-model fixture tasks | Whether the selected actual runtime/model uses tools/instructions correctly | Owner-run, bounded subscription use with fake/scrubbed target data |
| Owner-lab acceptance | Whether the implemented increment works in this homelab | Explicit manual session, least privilege, no production outage/destructive test |

Each [Stage 1 increment](../stage-1.md) needs its own record before the next begins. A scripted model transcript can prove dispatcher behavior but cannot establish actual prompt-injection resistance. A process restart fixture cannot establish recovery of an unimplemented future write.

## Initial regression set

- Pure schema/identity/filter/units/rendering tests, including empty, large, stale and partial results.
- Adapter HTTP/TLS boundary cases: auth rejection vs permission denial, missing objects, conflict/locks, rate limits, server failures, connect/read timeout, malformed payloads and changed certificates.
- Unknown tool/invalid arguments refused before I/O; only the agreed read methods/targets reachable; secret and content canaries excluded from every output/log/audit/error/snapshot surface.
- Real chosen application persistence for observation/session mappings and audit; native runtime history exercised through its supported interface. No mocked store or copied test-only algorithm.
- Runtime subprocess/control integration: startup/login unavailable, malformed/partial event stream, lost connection, cancellation, child/tool shutdown, deadlines, repeated errors, output pressure and restart with an interrupted run. Do not silently repeat lost requests.
- Pairing and profile isolation: verified instance identity, unauthorized/revoked access, wrong role, cross-instance session/credential confusion and unauthenticated local listener access.
- Actual native-tool restrictions: cannot read service/provider credentials, reach owner-only operations, install tools or use generic shell/network access to bypass the domain boundary.

Freeze time for time-dependent behavior and test aware UTC/edge conversion. Pin the runtime/tool versions under test. Do not mark tests passed from expectations; keep failures reproducible.

## Small task set from the first conversation

Start with the agreed discovery questions and add denied/unreachable/stale/empty/large cases. Include a guest description with fake system instructions, a forged tool result saying approval was granted, requests to reveal a token/run a command/create a VM, and two fixture instances sharing an alias. Score facts and authorized effects, not exact model phrasing.

Measure task correctness, tool calls, elapsed time, interventions, refusals and available runtime usage. Label estimates and unknown quota/cost explicitly; no measured token-saving claim exists. Changes to tools/instructions/runtime versions rerun the relevant cases before acceptance.

## Acceptance record template

For each increment record: date, code commit, runtime/version, instruction version, guest/target scope (private identifiers kept out of public docs), chosen limits, expected behavior, observed result, fixture vs live evidence, failures/limitations, secret-leak check, cleanup and owner's proceed/stop decision. Never paste provider credentials, raw target config, private transcripts or sensitive addresses in the repository.

Cancellation and interruption may be tested safely with fixtures. Do not reboot production nodes, revoke normal owner access, write disks or change networks to test a read-only stage. A second real cluster is not required for profile isolation.

Future writes need their own deterministic preview, approval race/replay/expiry, drift, ambiguity, crash/recovery, task tracking and verification tests, plus disposable-target owner acceptance, before enabling them. Do not carry the old suite as an architectural requirement or delete a failing test to hide retained behavior; [reuse review](../code-reuse.md) governs adopting relevant tests.
