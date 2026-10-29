# Origins

## Where this code came from

`agentic-assistant` started as the backend of **Aiva**, an AI personal-assistant startup idea built by a small team between late 2024 and mid-2026. The product never launched. The team included an iOS frontend that is not part of this repository.

This repository was created on 2026-10-29 by extracting `v2/backend` from the Aiva repository at commit `f4733e92da8c7451c83feb45f42128017b5faf2d` (2026-06-25). The contributors agreed to the extraction and to the MIT license.

- **Fresh history.** The Aiva history is not carried over, because it contains committed credentials. The Aiva repository itself remains intact.
- **Contributors.** Ivan Guo and Smarth Gupta wrote most of the backend, with smaller contributions from Tyler Buchanan. Line-level authorship can be checked in the Aiva repository with `git blame`.
- **AI tools.** Parts of the Aiva backend were written with AI coding assistants (Claude Code and Codex), with human review.

## What was inherited at extraction

- Django + DRF API with a planner (OpenAI) → orchestrator → tool registry pipeline.
- 60 registered tools across 7 OAuth integrations (Gmail, Google Calendar, Google Contacts, Google Drive, Outlook Mail, Outlook Calendar, Notion), plus weather, web search, local contacts, memory, and saved workflows.
- OAuth connect/finalize flow with encrypted credential storage; Celery + Redis scheduled workflows.
- 423 test methods, of which 256 ran under the original test runner.

A pre-extraction audit found gaps that this project is fixing; see the [roadmap](docs/roadmap.md). They include:
- OAuth scopes that didn't cover every Gmail tool
- retries that weren't idempotent
- test discovery that skipped the planner, orchestrator, and tool tests
- no CI
- no SMS, reminders, or incoming-mail detection

## What changed after extraction

See [CHANGELOG.md](CHANGELOG.md). Work done in this repository is by Smarth Gupta unless noted. The original Aiva design documents were not carried over; current documentation is in [`docs/`](docs/).
