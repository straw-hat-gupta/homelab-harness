# AGENTS.md

Steering guide for AI coding agents (and humans) working in this repository. Read it before making changes. If anything here conflicts with an explicit instruction from the maintainer, follow the maintainer and suggest an update to this file.

## Project

`agentic-assistant` is a self-hosted personal assistant backend built on Python 3.13, Django 5.2, DRF, PostgreSQL 16, and Celery with Redis. An LLM planner turns a request into a typed plan, and a deterministic orchestrator runs that plan against a registry of tools covering 7 OAuth integrations. Current state and plans:
- [docs/architecture.md](docs/architecture.md)
- [docs/roadmap.md](docs/roadmap.md): what to build next, plus the behavior rules for automatic actions

## Commands

```bash
pip install -r requirements.txt                      # install the pinned lock
python manage.py test                                # full suite; PostgreSQL required
python manage.py test tools.gmail --shuffle          # a subset, in random order
uvx ruff@0.7.4 check .                               # lint (config in ruff.toml)
python manage.py makemigrations --check --dry-run    # no missing migrations
python manage.py export_tool_reference               # regenerate docs/tools.md after changing tools
uv pip compile requirements.in --universal --python-version 3.13 -o requirements.txt  # after editing deps
```

Local setup and env values are in [docs/development.md](docs/development.md). CI runs lint, check, migrations, tests, gitleaks, and a Docker build, and must be green before a PR is reviewed.

## Architecture: Django-native layers

Don't impose onion or hexagonal architecture on Django; it fights the framework. Keep the part that matters: **business logic lives in plain functions, I/O stays at the edges, and dependencies point inward.**

| Layer | Where | Responsibility | May import |
|---|---|---|---|
| Interface | `views.py`, `serializers.py`, `urls.py`, `management/commands/`, `tasks.py` (Celery) | Parse and validate input, check permissions, call one service, shape the response. No business rules, ORM queries beyond simple ownership lookups, or provider calls. | services, selectors, serializers |
| Services | `<app>/services.py` (a package once it grows) | Use cases: orchestrate models, integrations, and pure logic. Own transactions (`transaction.atomic`), idempotency, and policy decisions. Keyword-only arguments, typed return values. | models, selectors, integrations, pure logic |
| Selectors | `<app>/selectors.py` | Read-only queries that return querysets or plain data, always scoped to a user. | models |
| Models | `<app>/models.py` | Schema, constraints, and small invariants on a single row (`is_expired()`, `clean()`). No HTTP, no LLM calls, no cross-app orchestration. | Django, other models |
| Integrations | `tools/<provider>/` and provider clients | Adapters to Google, Graph, Notion, OpenAI, Twilio. Explicit timeouts. Map provider errors to the shared exception types. Never touch the ORM directly; take what you need as arguments. | `requests`, SDKs, `tools.registry` |
| Pure logic | `<app>/<topic>.py` with **no Django imports** (for example time parsing, ICS parsing, classification rules) | Deterministic, unit-testable computation. | the standard library and small pure libraries |

Rules:
- Dependencies flow from interface to services to models, integrations, and pure logic. Nothing lower may import from views, serializers, or tasks.
- Celery tasks and management commands are as thin as views: load IDs, call a service, record the outcome.
- **Tools** (`ToolDef.fn`) are integration adapters invoked by the orchestrator. Keep them thin. Shared parsing and normalization goes in a helper module next to them, not in the tool function.
- New features follow this structure. When a PR already touches an existing module that mixes layers, move the code it changes into the right layer **if that stays within the PR's concern**. Don't do drive-by rewrites; propose a separate `refactor:` PR instead.
- Keep the existing app boundaries (`agent`, `planner`, `orchestrator`, `tools`, `plugins`, `workflows`, …). Add a new app only for a distinct domain (the roadmap's `assistant` app is one).

## Assistant-specific rules

These protect a system that can read private email and act on it.
- **Deterministic code decides; the LLM proposes.** Scheduling, time-zone and DST math, dedupe, idempotency, retries, policy, and notification recipients are plain code. LLM output is validated structured data (pydantic) and never directly triggers an external write.
- **Treat email and web content as untrusted.** Never let it choose tools, recipients, or actions. Keep tool access out of any prompt that contains raw email.
- **Confirmation.** Tools with outward or irreversible effects set `requires_confirmation=True`. Follow the behavior-rules table in [docs/roadmap.md](docs/roadmap.md#behavior-rules-for-milestones-1-and-3) for what may run automatically.
- **External writes must be safe to retry, or not retried.** Use provider idempotency (deterministic event IDs, `transactionId`) or a DB dedupe key. Never retry a non-idempotent write after an ambiguous failure (read timeout, 5xx).
- **Time.** Store aware UTC datetimes. Convert with `zoneinfo` at the edges. Never call `datetime.now()` without a tz; use `django.utils.timezone.now()`.
- **OAuth scopes.** Request the narrowest scope that covers a tool and declare it on the tool. A new tool must not need a scope its integration doesn't request.

## Coding practices

- **Style.** Match the surrounding code. Type hints on all new functions. Google-style docstrings (`Args:` / `Returns:`) on public functions, as the codebase already uses. Comments explain *why*, not what.
- **Functions.** Small and single-purpose. Return values instead of mutating arguments. Use keyword-only arguments for services with more than two parameters.
- **Errors.**
  - Raise specific exceptions (see `orchestrator/exceptions.py`).
  - Catch broadly only at boundaries (views, tasks, the orchestrator), and log with context there.
  - Never swallow an exception silently.
  - User-facing error messages must not leak provider responses or stack traces.
- **Logging.** Use the module logger (`logging.getLogger(__name__)`). Never log tokens, secrets, message bodies, or email or calendar content at INFO or above; IDs and counts are fine.
- **Configuration.**
  - Every setting is read from the environment in `backend/settings.py` with a safe default.
  - Each new variable is added to `.env.example` and `docs/configuration.md`.
  - No `os.getenv` scattered through app code for new settings.
- **Database.**
  - Every query on user data filters by the owner.
  - Use constraints for invariants (unique, check) rather than application-only checks.
  - Use `select_for_update` for state-machine transitions.
  - Avoid N+1 queries (`select_related`/`prefetch_related`).
- **Migrations.** One per logical change, generated by `makemigrations`, and reviewed. Never edit a migration that has already merged. Data migrations must be reversible or say why they aren't.
- **Dependencies.** Add them to `requirements.in` with a reason, then recompile the lock. Prefer the standard library and existing dependencies. A new framework, queue, or database needs a concrete requirement stated in the PR.
- **Security.** No secrets in code, fixtures, tests, or docs. Use placeholders such as `sk-test`. Validate all input with serializers or pydantic. Use `IsAuthenticated` plus ownership checks on every endpoint.
- **No dead code.** Don't leave commented-out code, unused helpers, or speculative abstractions. Remove what you replace.

## Testing

- **Every behavior change ships with tests** in the same PR: the success path plus the important failure modes (auth, validation, provider 401/403/404/429/5xx, duplicates, time-zone edges).
- **Tests never call real providers.** Mock at the HTTP or SDK boundary (`googleapiclient` mocks, patched `requests`, recorded JSON fixtures). Use the console notifier for SMS.
- **Pure-logic modules** get plain `SimpleTestCase` tests. **Services** get `TestCase` tests against Postgres.
- **Async code** in sync tests runs through `backend.testing.run_async`; plain `asyncio.run` leaks DB connections.
- **Throttled endpoints:** clear the cache in `setUp`.
- **Determinism.** Freeze time for anything time-dependent, and keep tests passing under `--shuffle`.
- **Don't game the suite.** Never skip, weaken, or delete a failing test to get green. Fix the cause, or explain in the PR why the test was wrong. Don't add tests just to raise a count.

## Documentation

- Update docs in the same PR as the behavior change. Docs describe what the code does **now**. Planned work goes in `docs/roadmap.md`.
- `docs/tools.md` is generated. Run `export_tool_reference`; a test fails if it is stale.
- Add a line under `## [Unreleased]` in `CHANGELOG.md` for user-visible changes.
- Don't claim something works against a real provider unless it was verified live. Say "mocked" or "unverified" otherwise.

## Git and pull requests

- **Never push to `main`, force-push shared branches, or merge PRs.** The maintainer merges.
- **Branch from the latest `main`**, named `<type>/<short-kebab-description>` (for example `feat/sms-outbox`, `fix/gmail-scopes`).
- **Conventional Commits** for commit messages and PR titles: `type(scope): imperative summary`.
  - Types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`, `ci`, `chore`, `revert`.
  - Scope is the app or area, e.g. `feat(reminders): …`, `fix(oauth): …`, `ci: …`, `chore(deps): …`.
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

1. `uvx ruff@0.7.4 check .` is clean.
2. `python manage.py test` passes on Postgres, exit code 0.
3. `python manage.py makemigrations --check --dry-run` reports no changes.
4. Docs, `.env.example`, `CHANGELOG.md`, and `docs/tools.md` are updated where relevant.
5. Report results faithfully. If something failed or was skipped, say so with the output.
