# ADR-0002: Python 3.13, FastAPI, SQLAlchemy and Postgres, in a uv workspace

- **Status:** accepted (2026-10-31)

## Context

The harness is an I/O-heavy control plane: HTTP calls to Proxmox and Cloudflare, SSH sessions, and an MCP server. Its domain types must validate strictly. The maintainer works in Python, and the official MCP SDK, DBOS and pydantic are all Python-first. A TypeScript stack was considered: Mastra or the AI SDK, with Drizzle. It would discard the maintainer's Python experience, and it offers nothing the harness needs, because the harness runs no model loop.

## Decision

| Concern | Choice |
|---|---|
| Runtime | Python 3.13 |
| Packaging | **uv workspace** (`packages/core`, `packages/sdk`, `capabilities/*`, `cli`) with one lockfile and hashed pins |
| Lint and format | ruff |
| Type checking | pyright in strict mode for `core` and `sdk`. ty may run alongside but does not gate, because it is still beta. |
| Web framework | FastAPI, with pydantic v2 and pydantic-settings |
| Data access | SQLAlchemy 2 (async, psycopg 3) |
| Migrations | Alembic |
| Database | Postgres 17 |
| Tests | pytest, pytest-asyncio, testcontainers (Postgres), respx (httpx mocking), hypothesis for parsers |
| CLI | Typer |

The future web UI will be TypeScript (React). See [ui.md](../spec/ui.md).

## Consequences

- Django's admin and auth go away. Owner auth is the OAuth authorization server ([ADR-0007](0007-owner-auth.md)), and admin tasks go through the CLI.
- Async is used throughout, so blocking libraries must be wrapped, or avoided entirely. This fixes the v0 async/sync class of bugs (R-01).
