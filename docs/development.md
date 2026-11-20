# Development at the documentation checkpoint

No implementation toolchain is active here. There is no `uv sync`, Python/UI test suite, link-check script, container build, dependency automation or application CI to run. Those files were intentionally retired with the implementation; do not recreate them just to validate documentation.

## Documentation work

Read [AGENTS.md](../AGENTS.md), [the active index](spec/README.md), [Stage 1](stage-1.md) and [ADR-0012](adr/0012-managed-agent-runtime-and-cli-first-stages.md). Update the owning contract rather than create overlapping plans. Label proposals, unimplemented behavior and future intentions. Do not write fake command examples as if installed today.

Before review:

- Verify the preservation branch and pinned source commit still resolve.
- Inspect the full tracked-file inventory: only Markdown, LICENSE/NOTICE and minimal Git metadata should remain at this checkpoint.
- Validate all relative Markdown paths and heading links, including retained historical documents. External URLs are checked where they substantiate current vendor claims; automated link counting is not a promise of external availability.
- Check entry-point navigation, instruction precedence, consistent runtime ownership and explicit Stage 1 exclusions.
- Compare S1–S10 with the preserved contract and review that no secrets protection was weakened.
- Check diff whitespace and scan new/modified docs for accidental credentials/private lab details.
- Record actual checks and omissions in [validation.md](validation.md).

Temporary validation tools may be used outside the repository. Do not commit an executable checker/workflow during a docs-only reset. `git diff --check` and `git ls-files` remain useful inspection commands; there is no application test run to claim.

## When code returns

Scope one accepted increment on its own branch. Pick only the runtime/library/store/build tools that increment needs, record why, add appropriate reproducible tests/checks and update commands/docs in the same change. [Code reuse](code-reuse.md) describes extracting proven pieces without reviving the old stack. Do not force framework shopping or a new security implementation merely to avoid old code.

Automated tests exercise fake network boundaries and real selected persistence. Actual runtime/model and owner-lab checks are separate, bounded sessions. Test cancellation, isolation and secret handling before enabling lab access. Do not carry historical test counts or dependency versions as targets for the restart.
