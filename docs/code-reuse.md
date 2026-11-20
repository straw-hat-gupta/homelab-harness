# Reuse from the preserved implementation

## Preserved source

The complete implementation is retained remotely on [archive/pre-cli-restart-2026-11-20](https://github.com/straw-hat-gupta/homelab-harness/tree/archive/pre-cli-restart-2026-11-20), pinned at `a97f2aacd611f0a6b666f336fda57fad88c27080`. It includes source, tests, dependency locks, vault, UI, deployment/CI configuration and all previous specifications. The restarted branch does not duplicate or depend on it.

Inspect a file without restoring the application using `git show archive/pre-cli-restart-2026-11-20:<path>` after fetching that branch, or use the pinned GitHub tree. The earlier Django code remains at `v0-django-final` and must not be restored. Earlier own-loop review/planning proposals are not binding.

## Requirement-first sequence

1. Identify the next accepted [Stage 1](stage-1.md) behavior and its safety/failure requirements.
2. Describe the smallest design independently of the old code: inputs, outputs, authority, storage and required evidence.
3. Search the relevant archived implementation, tests, fixtures and dynamic/configuration references. Do not label code dead solely from a missing direct import.
4. Evaluate correctness for current target/runtime versions, coupling, dependency/storage/auth assumptions, maintenance/security cost and license attribution.
5. Adopt only the necessary component with the relevant tests/fixtures. Rewrite a small adapter if simpler; never invent cryptography or bypass protections just to avoid dependencies.
6. Verify the actual new end-to-end path and owner acceptance. Historical green tests are evidence about the snapshot, not a guarantee of the new integration.

Record the decision in the implementation PR: requirement, candidate/source commit, dependencies retained/rejected, chosen boundary, relevant tests and unresolved limits. New architecture decisions need an ADR when they affect ownership or safety.

## Initial candidates

| Candidate | What may be useful | What is not automatically adopted |
|---|---|---|
| Proxmox adapter/TLS/parsers | Typed read mapping, verified TLS, safe errors, fixtures | All 18 tools, historical version assumptions, bootstrap write roles or full package framework |
| Vault | Tested envelope encryption, key handling, secret versions and protected persistence | Complete secret catalog, imports, grants UI, Postgres/API/auth stack without a current requirement |
| Redaction and validation | Secret canaries, safe messages, typed boundaries | Payload logging or blind trust in masking as isolation |
| Audit | Append-only records and allowlisted event data | Monitoring stack and payload-shaped session logs |
| CLI/API | Small transport/presentation helpers | Existing command layout, public OAuth architecture or duplicated domain logic |
| UI | Later reference for widgets and accessibility | Frontend assets, framework/toolchain, registries or build requirements in Stage 1 |
| DBOS/observability | Later reliability and instrumentation reference | A workflow engine driving the conversation or full monitoring deployment by default |

Preserving source is not adopting it. A reusable file lives only in the archive until a current requirement justifies it; do not add unused optional packages or a common/helpers library in anticipation.

## Historical code-free reset

The reset intentionally removes runtime source, tests, scripts, fixtures, dependency manifests/locks, deployment files, assets and executable workflows from the active tracked tree. Documents, legal notices and minimal Git metadata remain. Retirement is explicit and complete, with the snapshot preserved; it is not deletion of failing tests to manufacture green results.

It does not erase git history, untracked owner files, local environments, other worktrees, secrets or live database volumes. Future adoption happens on a scoped implementation branch, not by merging the old application branch wholesale.
