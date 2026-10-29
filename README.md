# agentic-assistant

A self-hosted personal assistant backend built with Python, Django, and Django REST Framework.

An LLM planner turns a natural-language request into a typed multi-step plan. A deterministic orchestrator then executes it against a registry of tools that call Gmail, Google Calendar, Drive, Contacts, Outlook, Notion, and more.

> **Status: early extraction.** This repository was just extracted from a team project. It runs and its test suite passes, but the personal-assistant features (incoming-mail triage, SMS alerts, interview calendar sync, natural-language reminders) are **not built yet**. Installation still requires Supabase. See [Roadmap](#roadmap) and [Known limitations](#known-limitations).

## What works today

- **Agent API.** `POST /agent/` and `POST /agent/stream/` (SSE) for plan → confirm → execute, with confirmation for irreversible actions.
- **Tool registry.** 60 registered tools across 7 OAuth integrations: Gmail 17, Google Calendar 6, Google Drive 4, Google Contacts 3, Outlook Mail 5, Outlook Calendar 5, Notion 7. Also 13 built-in tools: weather, web search, local contacts, memory, workflows, and an LLM processing step. None has been verified against a live provider yet.
- **OAuth.** Server-side one-time state, an authenticated finalize step, and Fernet-encrypted tokens at rest.
- **Workflows.** Saved workflows and cron-scheduled runs, executed by Celery workers.

## Running tests

Tests need PostgreSQL (some constraints and locking are Postgres-specific).

```bash
docker run -d --name aa-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16-alpine
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # placeholder values are fine for tests; set POSTGRES_* to the container above
python manage.py test
```

## CI/CD

| Workflow | Trigger | What it does |
|---|---|---|
| [`ci.yml`](.github/workflows/ci.yml) | Push to `main`, pull requests | Ruff (error-class rules), Django checks, migration drift check, the full test suite on Postgres 16, gitleaks scan of the whole history, and a Docker build that boots Django |
| [`release.yml`](.github/workflows/release.yml) | Push to `main`, `vX.Y.Z` tags | Runs CI, then publishes `ghcr.io/straw-hat-gupta/agentic-assistant` with tags `edge` and `sha-…` from `main`, and `X.Y.Z`, `X.Y`, `latest` from tags. Includes SBOM and provenance. |

To cut a release: `git tag v0.1.0 && git push origin v0.1.0`.

## Known limitations

- Authentication still uses Supabase-issued JWTs (being replaced with single-owner Django auth).
- The OAuth success redirect targets a mobile deep link (`aiva://…`). A browser-based connect page is planned.
- Gmail OAuth scopes do not yet cover the label, trash, and draft tools.
- Write tools may be retried without idempotency keys.
- Docker Compose expects an external Postgres.

## Roadmap

1. Interview radar and reminders: Gmail triage, SMS notifications, idempotent calendar sync, natural-language reminders, one-command install with Docker Compose.
2. Tool correctness and failure recovery across all 60 tools and 7 integrations: scopes, argument validation, safe retries, token refresh, contract tests, live smoke tests.
3. Safe multi-step chat: confirm resolved actions, untrusted-content boundary, policy for unattended runs.
4. Release: versioned images on GHCR, complete docs.

## Origins and license

Extracted from the Aiva team project with its contributors' permission. See [ORIGINS.md](ORIGINS.md) and [NOTICE](NOTICE). MIT licensed; see [LICENSE](LICENSE).
