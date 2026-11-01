# Development

## Requirements

- [uv](https://docs.astral.sh/uv/). CI pins 0.7.10, and newer versions work. uv installs Python 3.13 if it's missing.
- Docker, for the image and Compose, and for the database tests: they start a throwaway Postgres 17 with [testcontainers](https://testcontainers-python.readthedocs.io/). Without Docker they are skipped with a message; in CI (`CI` set) they fail instead.

## Workspace

One uv workspace with one lockfile (`uv.lock`, committed):

| Path | Distribution | Import |
|---|---|---|
| `packages/core` | `homelab-harness` | `homelab_harness` |
| `packages/sdk` | `homelab-harness-sdk` | `homelab_harness_sdk` |
| `cli` | `homelab-harness-cli` (installs `hh`) | `homelab_harness_cli` |
| `capabilities/proxmox` | `homelab-harness-proxmox` | `homelab_harness_proxmox` |

```bash
uv sync                                     # create .venv with every package editable + dev tools
uv run pytest                               # all tests
uv run pytest --cov                         # with coverage
uv run ruff check . && uv run ruff format .
uv run pyright                              # strict
uv add --package homelab-harness <dep>      # runtime dependency of core
uv add --dev <tool>                         # workspace dev tool
uv lock --upgrade-package <dep>             # bump one dependency
```

## Running the server

Settings come only from `HH_*` environment variables (`packages/core/src/homelab_harness/settings.py`). No `.env` file is read.

| Variable | Default | Meaning |
|---|---|---|
| `HH_ENV` | `prod` | `dev`, `test` or `prod`. `/docs` (OpenAPI UI) is served only outside `prod`. |
| `HH_HOST` | `127.0.0.1` | Bind address. The container sets `0.0.0.0` and publishes the port on loopback only. |
| `HH_PORT` | `8080` | HTTP port |
| `HH_LOG_LEVEL` | `INFO` | Minimum log level |
| `HH_LOG_FORMAT` | `json` | `json` (for Loki) or `console` |
| `HH_DATABASE_URL` | unset | Postgres URL, `postgresql://user:password@host:5432/db`. Unset means no database, DBOS or audit log (a warning is logged outside `test`). The password is registered with the redactor at startup and never logged. |
| `HH_DATABASE_POOL_SIZE` | `5` | Connections in the app's pool. DBOS keeps a second pool of the same size. |
| `HH_DATABASE_CONNECT_TIMEOUT_SECONDS` | `5` | Limit on opening a connection, and on waiting for a free one |
| `HH_DATABASE_STATEMENT_TIMEOUT_MS` | `15000` | Server-side `statement_timeout` on every app connection |
| `HH_CLI_URL` | `http://127.0.0.1:8080` | Where `hh` sends requests |

```bash
HH_ENV=dev HH_LOG_FORMAT=console uv run homelab-harness
curl -s localhost:8080/healthz      # liveness
curl -s localhost:8080/readyz       # readiness: ok | degraded | fail (503 only on fail)
uv run hh health
```

## Database

Postgres holds two things:
- **App tables** in `public`, migrated by Alembic. The scripts ship inside the package (`packages/core/src/homelab_harness/migrations/`), so the image can migrate itself.
- **DBOS system tables** in schema `dbos`. DBOS creates and migrates them itself when the harness starts.

The URL comes from `HH_DATABASE_URL`; there is no `alembic.ini`.

```bash
# a local Postgres for development (any free port; this is not the compose stack)
docker run -d --name hh-dev-pg -e POSTGRES_PASSWORD=devpass -p 127.0.0.1:5433:5432 postgres:17-alpine
export HH_DATABASE_URL=postgresql://postgres:devpass@127.0.0.1:5433/postgres

uv run homelab-harness-migrate upgrade              # to head (idempotent)
uv run homelab-harness-migrate current              # applied revision
uv run homelab-harness-migrate check                # fails if models and migrations disagree
uv run homelab-harness-migrate downgrade -1         # one step back
uv run homelab-harness-migrate revision --autogenerate -m "add plans"   # new script; review it
```

Startup with a database configured opens the engine, registers the `database` readiness check (`SELECT 1`), launches DBOS (recovering pending workflows) and registers the `dbos` check. If Postgres is down at startup, the process exits and its supervisor restarts it. If it goes down later, `/readyz` reports `database` and `dbos` as `fail` and returns 503.

**`audit_events` is append-only.** Triggers reject `UPDATE`, `DELETE` and `TRUNCATE` for every role except a superuser who disables them. In a hardened deployment, also run the harness as a role without `UPDATE`, `DELETE` or `TRUNCATE` grants on the table. The compose stack uses a single owner role for now. Audit `data` holds identifiers and counts only; the writer rejects payload-shaped input and redacts the rest.

## Container

```bash
export HH_POSTGRES_PASSWORD="$(openssl rand -hex 24)"   # required; there is no default
docker compose -f deploy/compose.yaml up -d --build
```

The stack has three services:
- `postgres`: Postgres 17 with the `pgdata` volume and a `pg_isready` healthcheck. It is not published on the host.
- `migrate`: a one-shot run of `homelab-harness-migrate upgrade`.
- `harness`: starts after Postgres is healthy and `migrate` has exited successfully.

The password is spliced into `HH_DATABASE_URL`, so use a URL-safe value; hex is.

The image is a two-stage uv build. It runs as uid 10001 with a read-only root filesystem and all capabilities dropped, and has a `HEALTHCHECK` on `/healthz`. CI builds it and checks `/healthz` on every PR. `release.yml` publishes `ghcr.io/straw-hat-gupta/homelab-harness` (`edge` from `main`, semver tags on releases) with SBOM and provenance.

## CI

| Job | What it checks |
|---|---|
| `lint` | ruff check, ruff format, pyright strict |
| `test` | pytest with coverage, against Postgres 17 in testcontainers (migration round trip and `alembic check` drift test included) |
| `audit` | `pip-audit --strict` against the exported runtime lock (R-26) |
| `docker` | The compose file is valid; the image builds and serves `/healthz` as a non-root, read-only container |
| `docs` | Relative Markdown links resolve |
| `secrets` | gitleaks over the full history |
