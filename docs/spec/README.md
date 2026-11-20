# Active specification

This directory describes the agreed target; **none of the restarted application is implemented here**. [Project status](../project-status.md) describes the repository now.

Binding reading order:

1. [Vision](vision.md) — product and non-goals.
2. [Stage 1](../stage-1.md) — exact next scope, increments and acceptance gates.
3. [Architecture](architecture.md) — runtime/service/client ownership and article layers.
4. [Clients and runtime integration](clients.md) — subscription login, pairing and local-model distinction.
5. [Onboarding](onboarding.md) — manually prepared guest and read-only discovery.
6. [Lab state and memory](lab-state.md), [steering](steering.md) — facts, instructions and history.
7. [Safety](safety-model.md), [secrets](secrets.md), [threat model](threat-model.md) — mandatory protections.
8. [Proxmox reads](capabilities/proxmox.md) — the initial tool boundary.
9. [Testing and evals](testing-and-evals.md), [reliability](reliability.md), [observability](observability.md) — evidence and honest outcomes.
10. [Extending](extending.md) and [code reuse](../code-reuse.md) — smallest appropriate additions.

[ADR-0012](../adr/0012-managed-agent-runtime-and-cli-first-stages.md) records the current decision. [Roadmap](../roadmap.md) orders delivery. [Glossary](../../GLOSSARY.md) defines terms. Proposals/open decisions are labelled and do not silently become implementation commitments.

[Future intentions](../future.md) are non-binding possibilities, not a parallel backlog. [Archives](../archive/README.md), the preserved implementation's docs and previous review branches are historical/non-binding. Their frontend, database, workflow-engine and external-client setup choices do not apply merely because they were once accepted.

Safety S1–S10 and secrets protections apply whenever the relevant feature exists and may only be strengthened. Deferring writes does not permit a different write path. If a new decision conflicts with these contracts, reconcile it explicitly before implementing it; safety changes need an ADR.
