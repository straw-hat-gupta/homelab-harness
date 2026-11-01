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
| `HH_OTEL_EXPORTER_OTLP_ENDPOINT` | unset | OTLP/HTTP base URL, e.g. `http://otel-collector:4318`. Unset or empty means telemetry off: no exporters, no instrumentation. See [Observability](#observability). |
| `HH_OTEL_EXPORT_TIMEOUT_SECONDS` | `5` | Limit on one export request |
| `HH_OTEL_METRIC_EXPORT_INTERVAL_SECONDS` | `15` | How often metrics are pushed |
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

The stack has three services by default:
- `postgres`: Postgres 17 with the `pgdata` volume and a `pg_isready` healthcheck. It is not published on the host.
- `migrate`: a one-shot run of `homelab-harness-migrate upgrade`.
- `harness`: starts after Postgres is healthy and `migrate` has exited successfully. Its compose healthcheck probes `/readyz`, so `docker ps` shows it unhealthy while the database is down. The image's own `HEALTHCHECK` (used outside compose) stays on `/healthz`.

The `observability` profile adds the Grafana stack; see [Observability](#observability).

The password is spliced into `HH_DATABASE_URL`, so use a URL-safe value; hex is.

The image is a two-stage uv build. It runs as uid 10001 with a read-only root filesystem and all capabilities dropped, and has a `HEALTHCHECK` on `/healthz`. CI builds it and checks `/healthz` on every PR. `release.yml` publishes `ghcr.io/straw-hat-gupta/homelab-harness` (`edge` from `main`, semver tags on releases) with SBOM and provenance.

## Observability

The harness exports traces, metrics and logs over OTLP/HTTP when `HH_OTEL_EXPORTER_OTLP_ENDPOINT` is set (ADR-0008, [observability.md](spec/observability.md)):
- **Traces:** one server span per HTTP request (FastAPI), a span per query on the app's engine (SQLAlchemy), and a client span per outgoing httpx request. Every span passes the redactor before export: sensitive keys and registered secret values are masked in names, attributes, events and status.
- **Metrics:** `http.server.request.duration` and friends from the same instrumentation, plus the app pool's `db.client.connections.usage`. The image sets `OTEL_SEMCONV_STABILITY_OPT_IN=http` so the stable HTTP names are used; export it too when running from source against the dashboards.
- **Logs:** every event still goes to stdout as JSON. With telemetry on, the same redacted JSON line is also sent over OTLP, carrying the active span's context. Events logged inside a span gain `trace_id` and `span_id` fields either way.

Log shipping uses OTLP from the process rather than tailing container log files. That needs no host mounts, no root and no Docker socket in the collector, works the same on Docker Desktop, and links log lines to traces natively. Only the harness's own logs are shipped; Postgres and the other containers stay in `docker logs`.

### Running the bundled stack

```bash
export HH_POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export HH_GRAFANA_ADMIN_PASSWORD="$(openssl rand -hex 16)"   # required; there is no default
export HH_OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
docker compose -f deploy/compose.yaml --profile observability up -d --build
```

| Service | Image | Reachable at | Config |
|---|---|---|---|
| `otel-collector` | `otel/opentelemetry-collector-contrib:0.164.0` | OTLP gRPC `127.0.0.1:4317`, HTTP `127.0.0.1:4318` | `deploy/otel/collector.yaml` |
| `prometheus` | `prom/prometheus:v3.15.1` | <http://127.0.0.1:9090> | `deploy/prometheus/prometheus.yaml` (native OTLP receiver, no scrape jobs) |
| `tempo` | `grafana/tempo:2.10.10` | compose network only | `deploy/tempo/tempo.yaml` (local storage, 7 days) |
| `loki` | `grafana/loki:3.7.9` | compose network only | `deploy/loki/loki.yaml` (filesystem, 14 days) |
| `grafana` | `grafana/grafana:13.2.5` | <http://127.0.0.1:3000>, user `admin` | `deploy/grafana/provisioning/`, dashboards in `deploy/grafana/dashboards/` |

Everything published binds to loopback; reach Grafana remotely with `tailscale serve`. Grafana has anonymous access and sign-up off, and refuses to start if `HH_GRAFANA_ADMIN_PASSWORD` is empty. A `${VAR:?}` guard is not used because compose would then demand the password even without the profile. The datasources (fixed UIDs `prometheus`, `tempo`, `loki`) link log lines to traces by `trace_id` and back. The provisioned **Harness overview** dashboard is read-only; change the JSON in the repo.

Prometheus maps `service.name` to the `job` label, so harness series carry `job="homelab-harness"`. In Loki the stream label is `service_name="homelab-harness"`, and `trace_id`/`span_id` are structured metadata.

Without the profile, nothing changes: leave `HH_OTEL_EXPORTER_OTLP_ENDPOINT` unset and the harness logs `telemetry_disabled` once and exports nothing.

### Using a stack the lab already runs

- **Existing collector:** skip the profile and set `HH_OTEL_EXPORTER_OTLP_ENDPOINT` to its OTLP/HTTP base URL (the harness appends `/v1/traces`, `/v1/metrics` and `/v1/logs`). The harness container must be able to reach it, for example on a shared Docker network or the host's LAN address.
- **Existing Prometheus, Tempo and Loki, no collector:** run only this collector and point its exporters at your backends:

  ```bash
  export HH_OTELCOL_PROMETHEUS_OTLP_URL=http://prom.lan:9090/api/v1/otlp/v1/metrics  # needs --web.enable-otlp-receiver
  export HH_OTELCOL_TEMPO_OTLP_GRPC=tempo.lan:4317
  export HH_OTELCOL_LOKI_OTLP_URL=http://loki.lan:3100/otlp/v1/logs                 # Loki 3 with structured metadata
  export HH_OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
  docker compose -f deploy/compose.yaml --profile observability up -d otel-collector harness
  ```

  Then import `deploy/grafana/dashboards/harness-overview.json` into your Grafana. It expects datasource UIDs `prometheus`, `tempo` and `loki`; adjust them on import if yours differ.

## CI

| Job | What it checks |
|---|---|
| `lint` | ruff check, ruff format, pyright strict |
| `test` | pytest with coverage, against Postgres 17 in testcontainers (migration round trip and `alembic check` drift test included) |
| `audit` | `pip-audit --strict` against the exported runtime lock (R-26) |
| `docker` | The compose file is valid with and without the `observability` profile; the image builds and serves `/healthz` as a non-root, read-only container |
| `docs` | Relative Markdown links resolve |
| `secrets` | gitleaks over the full history |
