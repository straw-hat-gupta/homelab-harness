# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added (vault persistence)
- The vault now persists: `secrets` (plain metadata, JSONB per kind) and `secret_versions` (ciphertext, nonces, wrapped DEK, KEK id; unique per secret and version), migration `0003`. `homelab_harness.secrets.service.VaultService` creates, rotates (new version; old ones kept), describes, lists, revokes, deletes and resolves secrets, and rewraps every DEK under the current KEK. Delete crypto-shreds: every version's ciphertext and wrapped DEK is deleted. Rewrap runs one transaction per version, so it can be interrupted and rerun, and a rerun changes nothing. Every operation is audited (`secret.created`, `.rotated`, `.revoked`, `.deleted`, `.used`, `vault.kek_rotated`) with names and ids only, never values, lengths or hashes.
- An owner REST API under `/api/secrets` and `/api/vault/rotate-kek`. It accepts only **owner-role** tokens: `homelab-harness-token create --client hh --role owner` (migration `0004` adds a `role` to client registrations; existing tokens become `mcp`). Owner tokens are refused at `/mcp` and MCP tokens at `/api`. No route returns a value, and 422 responses no longer echo rejected input.
- `hh secret add|list|show|rotate|revoke|delete|generate` and `hh vault rotate-kek`. Values come from a hidden prompt, `--stdin` or `--from-file`; a value on the command line is refused. `hh secret generate ssh_key` creates an ed25519 key inside the harness and prints only the public key and an `authorized_keys` line (optional `from=`). `hh` reads its token from `HH_CLI_TOKEN_FILE` or `HH_CLI_TOKEN`.
- The targets file accepts `token_secret = "secret://<name>"` in place of `token_secret_file`. Handles are resolved through the vault once at startup (audited as `secret.used`); a missing or revoked secret, or a Proxmox `token_id` that differs from the secret's, stops startup.
- The `vault` readiness check also queries the vault's tables once the database is open, and reports how many versions are still wrapped by an older KEK.
- Verified locally against a throwaway Postgres 17 with the env KEK provider: add, generate, rotate, KEK rotation and restart with only the new KEK, and a `secret://` target resolved at startup. Not verified with the file or systemd-creds providers, nor against a live Proxmox node.

### Changed
- The app enters its database lifespan before the MCP transport, so a startup error surfaces as itself rather than inside an exception group.

### Added (MCP server)
- An MCP server at `/mcp` on the harness app: streamable HTTP, stateless, JSON responses, built on the official MCP Python SDK (`mcp` 2.3). It serves protocol 2026-07-28 and the earlier handshake versions. Everything below is **mocked against Proxmox; not verified live** against a PVE node or against Claude Code or Codex. The SDK's own client was run against a local server.
- 18 Proxmox read tools (`proxmox.cluster.list`, `.cluster.resources`, `.node.list`, `.node.get`, `.guest.list`, `.guest.get`, `.storage.list`, `.storage.status`, `.storage.content`, `.disk.list`, `.disk.smart`, `.network.list`, `.pool.list`, `.ha.status`, `.backup.jobs`, `.task.list`, `.task.get`, `.metrics.rrd`). Each has JSON Schemas and `readOnlyHint`/`idempotentHint`, and returns structured content with `as_of` plus a text rendering. Target-sourced text sits in `untrusted` envelopes, and `_meta` flags it. Guest config is masked: passwords, tokens, keys, `args`, `hookscript` and `cicustom` show as `[MASKED]`, and SSH keys only as fingerprints.
- Capabilities are discovered through the `homelab_harness.capabilities` entry point. The SDK gains `@read_tool`, `ToolInput`, `ToolOutput`, `Untrusted`, `ToolContext`, `Capability`, `Manifest`, and the contract test kit `homelab_harness_sdk.testing` (extra `testing`).
- **Interim** target registration: `HH_TARGETS_FILE` names a TOML file of clusters, each with a per-tier `token_id` and an owner-only `token_secret_file`. Secrets are read once and registered with the redactor. `/readyz` gains `proxmox:<name>` checks, which report `degraded` when a cluster is unreachable.
- **Interim** MCP auth: per-client bearer tokens from `homelab-harness-token create|revoke|list` (new `mcp_clients` table, migration `0002`; only a SHA-256 hash is stored). Requests without a valid token get 401 with `WWW-Authenticate: Bearer`. **Tailnet only until OAuth (ADR-0007) lands.**
- Every tool call writes an `mcp.tool_call` audit event (client, tool, target, outcome, duration; no arguments). If the audit write fails, the call fails.
- The image now installs the Proxmox capability.

### Fixed
- The Proxmox adapter no longer hangs on a cyclic exception chain while looking for a TLS verification cause.
- httpx and httpcore loggers are held at WARNING. httpx's INFO request line carried the response reason phrase, where Proxmox puts its error text.

### Added (observability)
- OpenTelemetry traces, metrics and logs over OTLP/HTTP, turned on by `HH_OTEL_EXPORTER_OTLP_ENDPOINT` (off when unset or empty), with `HH_OTEL_EXPORT_TIMEOUT_SECONDS` and `HH_OTEL_METRIC_EXPORT_INTERVAL_SECONDS`. Spans and metrics come from FastAPI requests, the app engine's queries and outgoing httpx calls.
- Every span is redacted before export: span names, attributes, events, links and status pass the shared redactor (S9, R-16).
- Log events logged inside a span carry `trace_id` and `span_id`. With telemetry on, the same redacted JSON events are also exported over OTLP.
- `deploy/compose.yaml` gains an `observability` profile: OTel Collector, Prometheus, Tempo, Loki and Grafana, all pinned, with UIs on loopback only. Grafana needs `HH_GRAFANA_ADMIN_PASSWORD` (no default, anonymous access off). It provisions the datasources and a **Harness overview** dashboard: request rate, latency, 5xx share, readiness, pool, logs and recent traces.
- The compose `harness` healthcheck now probes `/readyz` instead of `/healthz`.
- The image sets `OTEL_SEMCONV_STABILITY_OPT_IN=http`, so it emits the stable HTTP metric names.

### Added (vault crypto core)
- `homelab_harness.secrets`: the vault's cryptographic core, with no persistence yet.
  - Envelope encryption: a random 256-bit DEK per secret version, AES-256-GCM with random 96-bit nonces, and the DEK wrapped by the KEK. Both layers bind `secret_id`, version and kind (the wrapped DEK also binds the KEK id) as associated data. KEK rotation rewraps DEKs without touching ciphertext. Any tampering, or the wrong KEK, raises `SecretIntegrityError`; there is no plaintext fallback.
  - KEK providers: a keyring file (refused unless it is mode 0400 and owned by the service user), systemd credentials, and an env variable for dev and test only (refused in prod). Selected with `HH_SECRETS_KEK_PROVIDER`. A configured provider that is missing or broken stops startup, and `/readyz` gains a `vault` check.
  - Typed models for the kinds `ssh_key`, `password`, `api_token`, `proxmox_token`, `cloudflare_token`, `github_token`, `file` and `kv`, separating encrypted fields from plain metadata. Values are wrapped so they never show in `repr`, formatting or dumps, and are registered with the redactor as soon as they are decrypted. SSH keys derive their public key and `SHA256:` fingerprint.

### Added (Proxmox read adapter)
- A new workspace package, `homelab-harness-proxmox` (`capabilities/proxmox`). It imports only the SDK. Everything below is **mocked; not yet verified live** against a PVE node.
- `ProxmoxClient`: an async, read-only Proxmox VE API client with typed pydantic models. It covers version, cluster status and resources, nodes and node status, node RRD metrics, QEMU and LXC lists, configs and status, storage config, status and content, disks and SMART, node network (with staged changes), pools, tasks with status and log (UPID-routed), HA status, and backup jobs.
- TLS verification is mandatory: a CA bundle, a pinned SHA-256 certificate fingerprint, or the system store. There is no insecure mode. A pinned certificate becomes the connection's only trust anchor, so a swapped certificate is refused before the token is sent.
- Proxmox failures map to the SDK error types (401, 403, 404/"does not exist", lock and conflict, 429 with `Retry-After`, 5xx/595, connect errors and timeouts). Messages never include response bodies, and the token secret never appears in `repr`, errors or logs.
- A pure UPID parser, and `render_bootstrap_script()`, which renders the `pveum` script for the `harness@pve` user, its custom roles, ACLs, and privilege-separated `read`, `guest-ops` and `provision` tokens (golden-file tested).
- A capability `manifest.toml` with the credential tiers.

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
- The container image is back on `python:3.13-slim`, the version CI tests. Dependabot now proposes only patch updates for the Python base image; minor and major upgrades move CI, the lock target and the image together in one deliberate PR.

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
