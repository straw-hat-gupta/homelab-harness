# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added (observability)
- OpenTelemetry traces, metrics and logs over OTLP/HTTP, turned on by `HH_OTEL_EXPORTER_OTLP_ENDPOINT` (off when unset or empty), with `HH_OTEL_EXPORT_TIMEOUT_SECONDS` and `HH_OTEL_METRIC_EXPORT_INTERVAL_SECONDS`. Spans and metrics come from FastAPI requests, the app engine's queries and outgoing httpx calls.
- Every span is redacted before export: span names, attributes, events, links and status pass the shared redactor (S9, R-16).
- Log events logged inside a span carry `trace_id` and `span_id`. With telemetry on, the same redacted JSON events are also exported over OTLP.
- `deploy/compose.yaml` gains an `observability` profile: OTel Collector, Prometheus, Tempo, Loki and Grafana, all pinned, with UIs on loopback only. Grafana needs `HH_GRAFANA_ADMIN_PASSWORD` (no default, anonymous access off). It provisions the datasources and a **Harness overview** dashboard: request rate, latency, 5xx share, readiness, pool, logs and recent traces.
- The compose `harness` healthcheck now probes `/readyz` instead of `/healthz`.
- The image sets `OTEL_SEMCONV_STABILITY_OPT_IN=http`, so it emits the stable HTTP metric names.

### Added (database)
- Postgres persistence for the core: an async SQLAlchemy engine (psycopg 3) with explicit pool limits and a statement timeout, configured by `HH_DATABASE_URL` and `HH_DATABASE_*`. The URL's password is registered with the redactor at startup.
- Alembic migrations shipped inside the package, run with the new `homelab-harness-migrate` command (`upgrade`, `downgrade`, `current`, `check`, `revision`).
- An append-only `audit_events` table. Triggers reject UPDATE, DELETE and TRUNCATE, and `seq` is a unique, database-assigned order (R-13). `AuditWriter.record()` validates and redacts each event before inserting it.
- DBOS is launched at startup when a database is configured, with its system tables in the `dbos` schema. `/readyz` gains `database` and `dbos` checks.
- `deploy/compose.yaml` adds `postgres` (17, with a volume and a healthcheck) and a one-shot `migrate` service. `HH_POSTGRES_PASSWORD` is required and has no default.
- Database tests run against real Postgres via testcontainers, in CI too.

### Added (Stage 1 skeleton)
- A uv workspace with three packages: `homelab-harness` (core), `homelab-harness-sdk` (shared error types, risk tiers, retry classes) and `homelab-harness-cli` (`hh version`, `hh health`).
- Core service:
  - FastAPI app with `/healthz`, and a `/readyz` that aggregates subsystem checks as ok, degraded or fail;
  - settings read only from `HH_*` environment variables, with no implicit `.env` loading;
  - structured JSON logging, where every event is redacted of sensitive keys and of registered secret values in common encodings.
- A container image that runs as non-root, with a read-only filesystem and all capabilities dropped. Also `deploy/compose.yaml`.
- CI jobs for ruff, strict pyright, pytest with coverage, pip-audit, a Docker build plus health check, docs links and gitleaks. The GHCR release workflow is restored with SBOM and provenance, and Dependabot now covers uv and Docker.
- `AGENTS.md` is rewritten as the code-level guide, and `docs/development.md` is added.

### Changed
- The GitHub repository is renamed to `straw-hat-gupta/homelab-harness`.

### Removed
- **BREAKING:** the v0 Django/DRF/Celery backend (all apps, dependencies, Docker image, Compose files, and the release workflow) is removed from `main` ahead of a rewrite. It is preserved at tag `v0-django-final`; its docs, the 2026-10-30 audit, and its 2026-10-31 cross-check moved to `docs/archive/v0/`.

### Decided
- The project is named **homelab-harness**, with an `hh` CLI. Owner auth is an embedded single-owner OAuth authorization server (ADR-0007, accepted).

### Added (secrets specification)
- `docs/spec/secrets.md` and ADR-0009 cover how secrets are handled:
  - a built-in envelope-encrypted vault;
  - grants per client and use mode, so agents use secrets by handle without seeing values;
  - SSH signing inside the harness, and egress routes that inject credentials;
  - owner intake through the CLI, a passkey-protected page, and MCP URL-mode elicitation.
- New reliability requirements R-34 to R-37, threat-model rows T-17 to T-19, and glossary terms.

### Added (rewrite specification)
- `docs/spec/` defines the rewrite as an AI control plane for Proxmox home labs:
  - vision, architecture, safety model, threat model, and client connections (bring your own subscription);
  - observability, reliability requirements R-01 to R-33, testing and evals, extending, steering, and the post-v1 UI;
  - capability specs for Proxmox, Linux and Docker, Cloudflare, and Obsidian.
- ADRs 0001–0008, `GLOSSARY.md`, and a staged `docs/roadmap.md` with open decisions.

### Changed
- CI checks documentation links and scans for secrets until code returns. Dependabot watches GitHub Actions only.

### Added
- Repository created from the Aiva backend (`Arceus-Aiva/Aiva@f4733e9`) with fresh history, MIT license, NOTICE, and ORIGINS.
- GitHub Actions CI: lint, Django checks, migration drift check, tests on Postgres, gitleaks, and a Docker build.
- `AGENTS.md` and `CLAUDE.md` steering docs (Django-native layering, assistant safety rules, coding and testing practices, Conventional Commits and PR conventions) and a PR template.
- Release workflow that publishes versioned images to GHCR after CI passes, with a build-only dry run on PRs that change it. Dependabot for Actions and pip.
- Documentation: architecture, configuration, HTTP API, development and CI/CD, roadmap.
- `manage.py export_tool_reference` generates `docs/tools.md` from the registry; a test fails when the file is stale.
- `requirements.in` with direct dependencies; `requirements.txt` is now a fully pinned uv lock, including previously unpinned transitive packages.

### Changed
- The tuning variables `PLANNER_TIMEOUT`, `PROCESSING_LLM_TIMEOUT`, `PROCESSING_LLM_MAX_TOKENS`, `TOOL_STEP_TIMEOUT`, `PLAN_CACHE_TTL`, `AGENT_THROTTLE_RATE`, `AGENT_MAX_MODIFY_REVISIONS`, and `PLANNER_USAGE_RETENTION_DAYS` are now read from the environment. They were documented before but ignored. Defaults are unchanged.
- Lint covers all pyflakes rules; inherited unused imports were removed.
- GitHub Actions updated to their current major versions (Node 24).

### Fixed
- Test discovery now runs every test (423 at extraction; previously 256). The suite passes on Postgres with exit code 0.
- Garbled characters (mojibake) and UTF-8 BOMs in several tool modules, including the `processing_llm` description shown to the planner.

### Removed
- About 40 unused dependencies (Flask, Supabase client libraries, MCP tooling, and others), plus the unused `SUPABASE_ANON_KEY` setting.
- Supabase login helper, unused prompt/server scripts, dead test helper, the Aiva GHCR image compose file, and the original Aiva docs.
