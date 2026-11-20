# Threat model

> **Status: binding review requirements; no mitigation is claimed implemented yet.** Review when an increment introduces an entry point, credential, runtime tool or storage boundary.

| Threat | Required mitigation / evidence |
|---|---|
| Wrong instance/cluster selected, changed server identity or reused alias | Authenticate and pin/verify the expected instance and target identity; scope sessions, observations and credentials independently of aliases; fixture-test collisions. |
| Unauthenticated LAN/loopback runtime listener | One encrypted authenticated owner connection; private runtime control channel; verify no unauthenticated reachable control endpoint. LAN/loopback is not identity. |
| Stolen/revoked client access remains usable on an open stream | Recheck authority when accepting messages/tool operations and end access after revocation; test reconnect and existing-session behavior. |
| Agent reads service/provider credentials or uses native tools around MCP | Effective runtime tool restrictions plus OS/process/file isolation; no target credential mount/read access; verify adversarial native filesystem/network attempts before lab access. |
| Agent accesses owner setup, widens grants or approves its work | Separate owner and tool principals; no owner API/approval tool in the runtime registry; verify all interfaces enforce it. |
| Prompt injection in names/descriptions/notes or stored context | Typed labelled untrusted data, deterministic authorization, owner-only instructions, bounded reads and real-model fixture evals. No model-selected authority. |
| Memory poisoning or stale observations treated as current fact | Separate writers/sources/freshness, no automatic agent memory edits, atomic updates, scoped refresh and explicit stale/partial state. |
| Credential leakage via errors, traces, transcripts or exports | Safe errors, no payload logging, encrypted broker storage and separate key backup, canary tests, private native-history retention/export; no automatic Git publication. |
| Subscription credential extraction/proxying or unsupported runtime use | Unmodified official binary, its own supported authentication, no wrapper credential-cache reads/direct inference proxy; verify current vendor conditions. |
| Infinite/repeated work, output flooding or orphaned child | Enforced run/call/time/context/output limits, repeated-error stop, independent tool deadlines and tested cancellation propagation. |
| Duplicate work after disconnect/restart | Persist native session mapping, mark interrupted state, no blind resubmission. Future writes need immutable plans, atomic claims and uncertain outcomes. |
| Compromised dependency or imported archived component | Requirement/dependency/security review, minimal pinned dependencies when code returns, canary/regression checks, target-enforced least privilege. |
| Future generated extension installs itself | Owner-reviewed draft/test/install process distinct from execution; trusted policy cannot be changed by target text or model code. |
| Future destructive/lockout/public exposure | Safety tiers/floors, deterministic preview, owner typed confirmation where required, re-preflight and verified access-preserving execution; separate disposable-target proof. |

The guest hosting the harness, provider state, target credentials, owner access, audit and private history are assets. Native runtime/OS capabilities and upstream model behavior are not assumed safe merely because the process is official. Mark actual limits of the selected runtime in acceptance evidence. The initial system has no public MCP endpoint, GUI, terminal proxy, collectors or background supervisor to secure.

Safety requirements are guarantees the implementation must prove for its enabled boundary; they are not a claim that prompt injection or host compromise is universally impossible. [Secrets](secrets.md), [safety](safety-model.md) and [testing/evals](testing-and-evals.md) define required defenses and evidence.
