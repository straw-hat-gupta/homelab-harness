# v0 archive: the Django backend

This folder keeps the documentation for v0, the Django 5.2, DRF, Celery, and OpenAI backend extracted from the Aiva project. The code was removed from `main` before the rewrite.

**Code:** the [`v0-django-final`](https://github.com/straw-hat-gupta/agentic-assistant/tree/v0-django-final) tag (commit `658e5f3`). To work with it locally, run `git checkout v0-django-final`.

At that tag, v0 had:
- 60 tools across 7 OAuth integrations;
- 425 passing tests;
- about 11.4k lines of runtime Python.

These documents describe v0 as it was. They are kept as history and as input to the rewrite, not as instructions for the current code.

| Doc | Contents |
|---|---|
| [audit-2026-10-30.md](audit-2026-10-30.md) | Repository audit: 20 findings, a deletion inventory, a performance review |
| [audit-cross-check-2026-10-31.md](audit-cross-check-2026-10-31.md) | Re-verification of that audit, a CVE scan, nine issues the audit missed |
| [architecture.md](architecture.md) | Request flow, planner and orchestrator, data model |
| [api.md](api.md) | HTTP endpoints and the confirmation flow |
| [configuration.md](configuration.md) | Environment variables |
| [development.md](development.md) | Local setup, tests, CI/CD |
| [roadmap.md](roadmap.md) | The v0 milestones and behavior rules, superseded by the rewrite |
| [tools.md](tools.md) | The generated reference for all 60 tools |

The v0 failure modes become the regression requirements of the rewrite. Each finding should map to a test that proves the new system doesn't have it.
