# AGENTS.md

Steering guide for AI coding agents (and humans) working in this repository. Read it before making changes. If anything here conflicts with an explicit instruction from the maintainer, follow the maintainer and suggest an update to this file.

## Project

**homelab-harness** is an AI control plane for Proxmox home labs. The owner's AI clients (Claude, ChatGPT) connect to it over MCP. The harness provides typed tools, plans with previews, out-of-band approvals, durable jobs, audit, and brokered secrets. It runs no model itself.

- **The spec is binding:** [`docs/spec/`](docs/spec/README.md), [`docs/adr/`](docs/adr/), [GLOSSARY.md](GLOSSARY.md).
  - [safety-model.md](docs/spec/safety-model.md) (S1–S10) and [secrets.md](docs/spec/secrets.md) may only be made stricter.
  - If code must contradict the spec, change the spec in the same PR. Add an ADR when the change touches safety.
- **What gets built when:** [`docs/roadmap.md`](docs/roadmap.md).
- **v0** (the Django assistant) is archived at tag `v0-django-final`, with its docs in `docs/archive/v0/` (history; don't edit). Port its logic by reading the tag. Never restore its code.

## Commands

```bash
uv sync                                   # install the workspace (Python 3.13, locked)
uv run pytest                             # all tests
uv run pytest packages/core -k readyz     # a subset
uv run ruff check . && uv run ruff format --check .
uv run pyright                            # strict type check
uv run homelab-harness                    # run the server (HH_* env vars; see settings.py)
uv run homelab-harness-migrate upgrade    # apply migrations (needs HH_DATABASE_URL)
uv run hh health                          # CLI against a running harness
docker compose -f deploy/compose.yaml up -d --build
python scripts/check_links.py             # docs links
uv add --package homelab-harness <dep>    # add a dependency to one package
```

## Layout

```
packages/core/   homelab_harness       control plane (FastAPI app, settings, logging, health, …)
packages/sdk/    homelab_harness_sdk   capability contract: errors, tiers, retry classes
cli/             homelab_harness_cli   `hh`, a thin REST client with no business logic
capabilities/    (Stage 1+)            proxmox, linux, docker, cloudflare, obsidian
deploy/          compose and observability config
docs/            spec, ADRs, roadmap, archive
```

See [architecture.md](docs/spec/architecture.md) for the full target layout.

## Layering rules

- **Capabilities import `homelab_harness_sdk` only, never `homelab_harness`.** Core discovers capabilities. This is the extension seam ([extending.md](docs/spec/extending.md)).
- **Interface code** (FastAPI routes, MCP handlers, CLI commands) parses input, calls one service, and shapes the response. It holds no policy and no queries beyond simple lookups.
- **Pure logic** (policy, preview rendering, parsers, redaction) has no I/O and no framework imports, and gets plain unit tests.
- **Adapters** talk to targets with explicit timeouts and map every failure to `homelab_harness_sdk.errors`. They never touch the database and never decide policy.
- **Writes to targets happen only in executor steps run by jobs** (S1). A tool function never performs a write.

## Rules that protect the lab

- **The model proposes; deterministic code decides.** Tiers, approvals, retries and previews are code.
- **No tool returns a secret value**, and none decides approval (S2, S9). Agents use `secret://` handles.
- **Target-sourced text is untrusted data** (S7). Never branch on it to choose an action.
- **Retries:**
  - Steps declare a `RetryClass`.
  - `UNSAFE` steps run at most once. An ambiguous result raises `AmbiguousOutcome`, and the job ends as `uncertain`.
  - Only `AuthRejected` may mark a credential unusable (R-14).
- **Time:** use aware UTC internally and `zoneinfo` at the edges. Never call a naive `datetime.now()`. Ruff's `DTZ` rules enforce this.
- **Logging:**
  - Use `structlog.get_logger(__name__)`.
  - Log identifiers and counts, never payloads, note bodies, or command output.
  - Redaction is a safety net, not a licence to log sensitive data.
- **Settings:** add fields to `homelab_harness.settings.Settings` (the `HH_` prefix). Never read `os.environ` elsewhere, and never load `.env` implicitly (R-24).

## Coding practices

- Type hints everywhere; `pyright` runs in strict mode in CI. Google-style docstrings (`Args:`, `Returns:`, `Raises:`) on public functions. Comments explain *why*.
- Keep functions small. Use keyword-only arguments for anything with more than two parameters. Return values instead of mutating arguments.
- Raise the shared error types, and catch broadly only at boundaries (routes, jobs), logging with context.
- Owner-facing messages never include provider bodies, URLs with credentials, or stack traces.
- Dependencies: prefer the standard library and existing dependencies. Add with `uv add --package …`, giving a reason in the PR. The lock (`uv.lock`) is committed, and CI runs `pip-audit` against it.
- No dead code and no speculative abstractions.

## Testing

- **Every behavior change ships with tests:** the success path plus the failure modes that matter (auth, validation, 401/403/404/409/429/5xx, timeouts, ambiguity, duplicates, time-zone edges).
- **No test calls a real target.** Mock at the HTTP boundary (`respx`), or use recorded, scrubbed fixtures. Live runs against a nested Proxmox are a separate, manual suite.
- **Pure logic** gets plain pytest. **Services** test against real Postgres, using the testcontainers fixtures in `packages/core/tests/conftest.py`. Never mock the persistence boundary (R-01).
- **Redaction:** a capability's tests include the canary-secret check.
- **Determinism:** freeze time for anything time-dependent. Tests must pass in any order.
- **Don't game the suite.** Never skip, weaken or delete a failing test to get green. Fix the cause, or explain in the PR why the test was wrong.
- When a test proves a reliability requirement, fill in its "Test" cell in [reliability.md](docs/spec/reliability.md).

## Documentation

- Docs describe what the code does **now**. When code implements a spec section, update that section in the same PR.
- Add a line under `## [Unreleased]` in `CHANGELOG.md` for user-visible changes.
- Don't claim something works against a real system unless it was verified live. Say "mocked" or "unverified" otherwise.
- No secrets in docs or examples. Use placeholders.

## Git and pull requests

- **Never push to `main`, force-push shared branches, or merge PRs.** The maintainer merges.
- **Branch from the latest `main`**, named `<type>/<short-kebab-description>` (for example `feat/proxmox-tasks`, `docs/threat-model`).
- **Conventional Commits** for commit messages and PR titles: `type(scope): imperative summary`.
  - Types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`, `ci`, `chore`, `revert`.
  - Scope is the area, e.g. `docs(spec): …`, `feat(proxmox): …`, `ci: …`, `chore(deps): …`.
  - Breaking changes use `!` and a `BREAKING CHANGE:` footer.
- **Commits:**
  - Each one is a coherent, buildable step with a body that explains *why*.
  - Commits written with an AI agent keep a `Co-Authored-By:` trailer naming the model.
  - Don't commit generated junk (`__pycache__`, `.env`, local databases).
- **PRs:**
  - **One concern per PR.**
  - Open it **ready for review**, after running the checks locally.
  - Keep it reviewable; split mechanical changes (renames, formatting) from behavior changes.
  - CI must be green before you ask for review. If CI fails, fix it in a new commit on the branch.
- **PR description** follows [the template](.github/pull_request_template.md):
  - **Summary:** what changed and why.
  - **Test plan:** a checklist of exactly what was run and its result.
  - **Notes:** follow-ups, risks, unverified behavior.
- **Do not add "Generated with Claude Code" or any similar tool-attribution footer to PR descriptions.**
- **Dependabot PRs:** don't hand-edit them; supersede them with a deliberate `chore(deps):` PR when needed.

## Before you say a task is done

1. `uv run ruff check . && uv run ruff format --check .` is clean.
2. `uv run pyright` reports 0 errors.
3. `uv run pytest` passes (quote the count).
4. If you touched the Dockerfile or deploy files: the image builds and `/healthz` answers.
5. Docs, `CHANGELOG.md`, and the `reliability.md` Test cells are updated where relevant. `python scripts/check_links.py` is clean.
6. Report results faithfully. If something failed or was skipped, say so with the output.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `straw-hat-gupta/homelab-harness` (gh CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` and `docs/adr/`, created lazily. See `docs/agents/domain.md`.
