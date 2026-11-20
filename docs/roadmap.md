# Roadmap

Each increment ends in something the owner tries. Completion is evidence, not a subsystem checklist, test-count target or elapsed time. No calendar estimates or automatic stage progression.

| Stage | Functionality | Gate |
|---|---|---|
| 0: reconcile documentation | Documentation-only repository; official-runtime wrapper direction; archived implementation; precise first-stage scope | Documents agree, preservation verified and documentation checks pass. No runtime capability is claimed. |
| 1A | Subscription-backed official runtime on the service guest, fixture tool, supported instructions/streaming/control | Owner verifies runtime behavior and native-tool/credential boundaries before real lab access. |
| 1B | Typed deterministic cluster/node/guest/storage discovery | Owner compares real facts/units with Proxmox; fixture failures and secret handling pass. |
| 1C | Thin Mac CLI with saved instance selection and private authenticated connection | Owner verifies connection/reconnect, identity and revoked-access refusal. |
| 1D | Natural-language discovery through restricted tools | Real model returns verified facts; bounded failures and malicious fixture text are handled. |
| 1E | Native history, memory boundaries, refresh and restart/reconnect | Owner proves client replacement/restart preserves history and marks interrupted/stale state honestly. |
| 2: one observed improvement | Choose one task-driven need, such as capacity checks, setup friction, compact context or a second runtime | Demonstrated improvement without breaking Stage 1. Define this stage only after using Stage 1. |
| 3: one controlled write | One VM-create-from-template operation on a disposable scope | Plan, deterministic preview, explicit owner approval, re-preflight, durable execution, ambiguity handling and verification proven before owner-lab use. No auto-approval initially. |
| Later | Reusable operations, reviewed extensions, GUI, roles/jobs, local/VPS inference and additional domains | Select one need at a time and write its own scope/tests/live gate. None is required just to label a release complete. |

[Stage 1](stage-1.md) is the single detailed contract for the first implementation. [Future intentions](future.md) preserve direction without prescribing a platform. A GUI can follow a stable useful core independently of other future features; no frontend work is required now.

## Evidence rule

Automated tests use fake model/target boundaries and the real chosen local persistence. Live-model runs and owner-lab checks are separate, intentional sessions. Each acceptance record names version, scope, expected/observed results, failures and the owner's proceed/stop decision. An owner can explicitly accept a bounded usability limit; a safety invariant cannot be waived by a casual stage sign-off.

## Current next action

After the documentation reset is merged, scope 1A alone. Decide its runtime/guest/control/limit choices, inspect only relevant reusable components and build the smallest fixture-backed proof on a separate branch. Do not import the old UI, full API platform or dependency stack before a current requirement justifies it.
