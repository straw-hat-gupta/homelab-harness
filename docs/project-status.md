# Project status

Reviewed 2026-11-20. **This branch contains documentation, legal notices and minimal Git metadata only.** No application source, installer, dependency lock, deployment, fixture suite, executable workflow or frontend is active. No Stage 1 acceptance box is complete.

The intended product is described in the [vision](spec/vision.md) and [Stage 1 contract](stage-1.md): a thin Mac client connects to a cluster-side service which runs one unmodified official agent runtime with read-only Proxmox tools. The runtime owns its loop/authentication/history; the harness owns lab context, tools and domain authorization.

## Current evidence

Documentation checks are recorded in [validation.md](validation.md). There is no current Python/UI test count, live-runtime support or cluster verification to report. Published vendor capabilities are design inputs, not evidence that our wrapper works.

## Historical implementation

The full [snapshot](code-reuse.md#preserved-source) at `a97f2aa` contains the earlier MCP-first service, thin management CLI, encrypted vault, authentication/OAuth, audit, 18 read tools, DBOS foundation, observability and read-only React UI. Prior automated results belong to that implementation. Neither its breadth nor its tests decide what the restarted application must contain.

Old language saying Stage 1 was built referred to that retired platform stage. The new 1A–1E milestones are unimplemented. No live infrastructure/data has been deleted by retiring tracked code; local environments/worktrees are not part of the branch's application inventory.

## Next

Merge the documentation-only reset through maintainer review, then scope 1A alone. Confirm the runtime/version, supported guest/control surface, isolation and numerical bounds; inspect relevant archived pieces only after defining that proof. Do not resume the old GUI/platform backlog. The [roadmap](roadmap.md) gates each subsequent increment on owner use.
