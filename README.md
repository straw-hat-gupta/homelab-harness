# agentic-assistant

[![CI](https://github.com/straw-hat-gupta/agentic-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/straw-hat-gupta/agentic-assistant/actions/workflows/ci.yml)
[![Release image](https://github.com/straw-hat-gupta/agentic-assistant/actions/workflows/release.yml/badge.svg)](https://github.com/straw-hat-gupta/agentic-assistant/actions/workflows/release.yml)

A self-hosted personal assistant backend built with Python, Django, and Django REST Framework.

An LLM planner turns a natural-language request into a typed multi-step plan. A deterministic orchestrator executes it against a registry of tools for Gmail, Google Calendar, Drive, Contacts, Outlook, Notion, and more, injecting credentials, passing results between steps, retrying transient failures, and asking for confirmation before irreversible actions.

> **Status: early.** The agent, tools, OAuth, and scheduled workflows run, and the test suite passes in CI. The personal-assistant features (incoming-mail triage, SMS alerts, interview calendar sync, natural-language reminders) are **not built yet**, and authentication still uses Supabase-issued tokens. See the [roadmap](docs/roadmap.md) and [known limitations](#known-limitations).

## What works today

- **Agent API.** `POST /agent/` and `/agent/stream/` (SSE): plan → confirm → execute, with conversation history and persistent user memories.
- **60 registered tools across 7 OAuth integrations:** Gmail 17, Google Calendar 6, Google Drive 4, Google Contacts 3, Outlook Mail 5, Outlook Calendar 5, Notion 7. Plus 13 built-in tools: weather, web search, local contacts, memory, workflows, and an LLM processing step. See the [tool reference](docs/tools.md). None has been verified against a live provider yet.
- **OAuth.** Single-use server-side state, a finalize step bound to the user who started the flow, and Fernet-encrypted tokens with key rotation.
- **Workflows.** Saved plans with typed inputs, cron schedules in any IANA time zone, and Celery workers.
- **CI/CD.** Lint, tests on Postgres, a secret scan, and an image build on every PR. Versioned images published to GHCR from `main` and release tags.

## Quick start (development)

```bash
docker run -d --name aa-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16-alpine
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # see docs/development.md for local values
python manage.py migrate
python manage.py test
```

## Documentation

| Doc | Contents |
|---|---|
| [Architecture](docs/architecture.md) | Request flow, planner and orchestrator, integrations, background work, data model |
| [Configuration](docs/configuration.md) | Every environment variable, with required/optional status and defaults |
| [HTTP API](docs/api.md) | Endpoints, the confirmation flow, error codes |
| [Tool reference](docs/tools.md) | All 60 tools, generated from the registry |
| [Development](docs/development.md) | Local setup, tests, lint, dependencies, CI/CD, releases |
| [Roadmap](docs/roadmap.md) | Milestones and the behavior rules being implemented |
| [AGENTS.md](AGENTS.md) | Contributor and AI-agent guide: layering, coding practices, testing, commit and PR conventions |

## Known limitations

- Authentication uses Supabase-issued JWTs, and any valid token gets an account. Single-owner Django auth is planned.
- The OAuth success redirect targets a mobile deep link (`aiva://…`), so connecting accounts needs a client that handles it. A browser connect page is planned.
- Gmail OAuth scopes (`gmail.readonly`, `gmail.send`) do not cover the label, mark-read, trash, and draft tools.
- Write tools can be retried without idempotency keys; saved and scheduled workflow runs skip the confirmation step.
- Docker Compose does not include PostgreSQL.

## Origins and license

Extracted from the Aiva team project with its contributors' permission. See [ORIGINS.md](ORIGINS.md) and [NOTICE](NOTICE). MIT licensed; see [LICENSE](LICENSE).
