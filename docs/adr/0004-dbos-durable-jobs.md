# ADR-0004: DBOS for durable jobs, schedules and reminders; no Celery or Redis

- **Status:** accepted (2026-10-31)

## Context

Applying a plan is a multi-step workflow. It waits on Proxmox tasks that can run for minutes, and it must survive restarts without repeating an external write. v0's Celery dispatch could run the same job twice and lose jobs it had queued but never dispatched (v0 findings #2 and #7). The options were Temporal, DBOS, Restate, Inngest, and Celery with a hand-written state machine.

## Decision

Use **DBOS** (Python, MIT-licensed, Postgres-backed) for:
- jobs, where the workflow ID is the plan ID;
- external task polling;
- scheduled syncs;
- reminders, using durable sleep;
- per-scope concurrency, using queues keyed by target scope.

Each executor step declares a retry class:
- `read` and `idempotent` steps may be retried.
- `unsafe` steps run at most once. If recovery finds one started but not recorded as finished, the job ends as `uncertain` and is not replayed.

## Alternatives

- **Temporal:** the industry standard, and a stronger "brand" signal. It needs a separate server cluster, which is too heavy for a single-owner home lab.
- **Restate, Inngest:** BSL licensing for self-hosting, and less Python maturity.
- **Celery + Redis:** no durable workflow semantics, which was the source of the v0 bugs.

## Consequences

- The deployment is one app process plus Postgres. Workflow state is queryable in SQL, so Grafana can read it.
- DBOS's at-least-once step semantics mean the `unsafe` handling must be explicit and tested (R-02, R-11).
