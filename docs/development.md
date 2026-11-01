# Development

## Requirements

- [uv](https://docs.astral.sh/uv/). CI pins 0.7.10, and newer versions work. uv installs Python 3.13 if it's missing.
- Docker, for the image and Compose. Later stages also use it for Postgres in tests (testcontainers).

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
| `HH_CLI_URL` | `http://127.0.0.1:8080` | Where `hh` sends requests |

```bash
HH_ENV=dev HH_LOG_FORMAT=console uv run homelab-harness
curl -s localhost:8080/healthz      # liveness
curl -s localhost:8080/readyz       # readiness: ok | degraded | fail (503 only on fail)
uv run hh health
```

## Container

```bash
docker compose -f deploy/compose.yaml up -d --build
```

The image is a two-stage uv build. It runs as uid 10001 with a read-only root filesystem and all capabilities dropped, and has a `HEALTHCHECK` on `/healthz`. CI builds it and checks `/healthz` on every PR. `release.yml` publishes `ghcr.io/straw-hat-gupta/homelab-harness` (`edge` from `main`, semver tags on releases) with SBOM and provenance.

## CI

| Job | What it checks |
|---|---|
| `lint` | ruff check, ruff format, pyright strict |
| `test` | pytest with coverage |
| `audit` | `pip-audit --strict` against the exported runtime lock (R-26) |
| `docker` | The image builds and serves `/healthz` as a non-root, read-only container |
| `docs` | Relative Markdown links resolve |
| `secrets` | gitleaks over the full history |
