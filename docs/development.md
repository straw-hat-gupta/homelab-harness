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
| `HH_SECRETS_KEK_PROVIDER` | unset | Vault KEK source: `file`, `systemd-creds` or `env`. Unset means no vault (and no `vault` readiness check). A configured provider that is missing or broken stops startup. |
| `HH_SECRETS_KEK_FILE` | unset | Keyring file for the `file` provider. Refused unless it is mode 0400, owned by the service user (or root), and not a symlink. |
| `HH_SECRETS_KEK_CREDENTIAL` | `hh-kek` | Credential name for the `systemd-creds` provider, read from `$CREDENTIALS_DIRECTORY/<name>` |
| `HH_SECRETS_KEK` | unset | Keyring for the `env` provider, entries separated by commas. **Dev and test only:** refused when `HH_ENV=prod`, and `/readyz` reports `vault` as degraded. |
| `HH_OTEL_EXPORTER_OTLP_ENDPOINT` | unset | OTLP/HTTP base URL, e.g. `http://otel-collector:4318`. Unset or empty means telemetry off: no exporters, no instrumentation. See [Observability](#observability). |
| `HH_OTEL_EXPORT_TIMEOUT_SECONDS` | `5` | Limit on one export request |
| `HH_OTEL_METRIC_EXPORT_INTERVAL_SECONDS` | `15` | How often metrics are pushed |
| `HH_TARGETS_FILE` | unset | **Interim** TOML list of targets per capability, with each credential's vault handle or secret file. See [MCP server](#mcp-server). Unset means no targets: tools answer "no proxmox target is registered". An invalid file, or a handle naming a missing or revoked secret, stops startup. |
| `HH_PUBLIC_URL` | unset | The harness's HTTPS origin as clients reach it (`https://<host>.<tailnet>.ts.net`; `http://localhost:<port>` in dev). It is the OAuth issuer, the passkey relying party and the origin of the MCP resource `<url>/mcp`. Must be an origin (no path) and HTTPS unless loopback. Unset means no owner login and no OAuth: `/mcp` takes only legacy tokens. See [Owner login and OAuth](#owner-login-and-oauth). |
| `HH_MCP_LEGACY_TOKENS` | `true` | Whether `/mcp` still accepts `homelab-harness-token` MCP tokens. Will default to `false` once OAuth is verified with live clients. `false` without `HH_PUBLIC_URL` stops startup. |
| `HH_OAUTH_ACCESS_TOKEN_SECONDS` | `900` | Access token lifetime (60 to 3600) |
| `HH_OAUTH_REFRESH_TOKEN_SECONDS` | `2592000` | Refresh token lifetime (30 days); each use rotates it |
| `HH_OAUTH_DCR_ENABLED` | `true` | Serve `/oauth/register` (dynamic client registration, the fallback to client metadata documents) |
| `HH_OWNER_SESSION_IDLE_SECONDS` | `900` | Owner browser session idle timeout |
| `HH_OWNER_SESSION_MAX_SECONDS` | `43200` | Owner browser session absolute lifetime |
| `HH_CLI_URL` | `http://127.0.0.1:8080` | Where `hh` sends requests |
| `HH_CLI_TOKEN_FILE` | unset | File holding only the owner token `hh` sends to `/api` (chmod 0600; looser modes are refused). See [Vault](#vault). |
| `HH_CLI_TOKEN` | unset | The owner token itself, when no file is set. Child processes inherit it, so prefer the file. |

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

## Dev KEK

The vault's key-encryption key (KEK) never goes to Postgres. Every provider reads a keyring: one `kek_id:base64key` entry per line (or comma), **newest first**. The first entry wraps new data keys, and older entries stay so that secrets wrapped before a rotation still open. Blank lines and `#` comments are ignored. Each key must decode to exactly 32 bytes.

```bash
# a throwaway KEK for local work, in the env provider (dev and test only)
export HH_ENV=dev HH_SECRETS_KEK_PROVIDER=env
export HH_SECRETS_KEK="$(uv run python -c 'from homelab_harness.secrets.keys import generate_kek, keyring_line; print(keyring_line(generate_kek("dev-1")))')"

# or a key file, as production uses it
(umask 077; printf 'dev-1:%s\n' "$(openssl rand -base64 32)" > ~/.config/hh-kek)
chmod 0400 ~/.config/hh-kek          # owner read-only; any other mode is refused
export HH_SECRETS_KEK_PROVIDER=file HH_SECRETS_KEK_FILE=~/.config/hh-kek
```

With systemd, store the keyring as an encrypted credential (TPM2-sealed when the host has a TPM) and load it with `LoadCredentialEncrypted=hh-kek:/etc/credstore.encrypted/hh-kek`; set `HH_SECRETS_KEK_PROVIDER=systemd-creds`. This path is unverified on a real host so far.

Losing the KEK loses every secret: back the keyring up separately from the database.

## Vault

With both `HH_DATABASE_URL` and `HH_SECRETS_KEK_PROVIDER` set, the harness stores secrets in Postgres (`secrets` for plain metadata, `secret_versions` for the sealed values; migration `0003`) and serves the owner API under `/api/secrets` and `/api/vault`. `hh` is its client. No route returns a value, a length or a hash, and there is no reveal command yet.

**Owner token.** The API accepts only tokens created with the `owner` role. Owner tokens are refused at `/mcp`, and MCP tokens are refused at `/api`, so a token pasted into an AI client can never manage the vault (migration `0004` adds the role; existing tokens become `mcp`).

```bash
(umask 077; uv run homelab-harness-token create --client hh --role owner > ~/.config/hh-token)
export HH_CLI_TOKEN_FILE=~/.config/hh-token HH_CLI_URL=http://harness.tailnet:8080
```

**Commands.** Values come from a hidden prompt (asked twice), `--stdin` or `--from-file`. `hh` refuses a value on the command line, where shell history and `ps` would keep it.

```bash
hh secret add pve-home-read --kind proxmox_token --meta 'token_id=harness@pve!read'   # hidden prompt
op read op://Lab/pve/token | hh secret add pve-home-read --kind proxmox_token --stdin --meta 'token_id=harness@pve!read'
hh secret add kube --kind file --from-file ~/.kube/config            # filename from the path; size derived
hh secret add app-env --kind kv --key API_KEY --key DB_PASSWORD      # one hidden prompt per key
hh secret add app-env --kind kv --stdin < app.env                    # or KEY=VALUE lines
hh secret add gh --kind github_token --meta-json '{"repos": ["me/vault"], "expires_at": "2027-01-01T00:00:00Z"}'
hh secret generate ssh_key docker-01-deploy --comment deploy --from 10.0.0.5   # prints the public key only
hh secret list
hh secret show pve-home-read             # metadata and versions, never the value
hh secret rotate pve-home-read           # new version; older versions are kept
hh secret rotate docker-01-deploy --generate
hh secret revoke pve-home-read           # unusable until rotated
hh secret delete pve-home-read           # asks you to type the name; --confirm NAME for scripts
hh vault rotate-kek                      # rewrap every data key under the current KEK
```

Kinds and their rules are in [secrets.md](spec/secrets.md#secret-kinds). Metadata is plain text: it is shown to the owner and, later, to agents, so never put a value in it. `ssh_key` metadata (public key, fingerprint), `kv` key names and `file` sizes are derived from the value. Every operation writes an audit event (`secret.created`, `.rotated`, `.revoked`, `.deleted`, `.used`, `vault.kek_rotated`) with names and ids only.

**Rotating the KEK.**
1. Put the new entry first in the keyring and keep the old one after it; restart the harness. `/readyz` now reports `N version(s) on an older KEK`.
2. Run `hh vault rotate-kek`. Each version is rewrapped in its own transaction, so an interrupted run can simply be repeated; a repeat reports `0 rewrapped`. It exits 1 if any version failed.
3. When it reports `0 failed`, remove the old entry and restart.

**Deleting** destroys every version's ciphertext and wrapped data key (crypto-shred). Copies of those rows can survive in Postgres's WAL, in dead tuples until vacuum, and in backups; they stay unreadable once the KEK that wrapped them is rotated out and destroyed.

## MCP server

The harness serves MCP at `/mcp` (streamable HTTP, stateless, JSON responses). It speaks the 2026-07-28 protocol and the earlier handshake versions. It needs `HH_DATABASE_URL`, because client tokens and the audit log live in Postgres. Without a database every request gets 401.

> **Tailnet only.** Clients authenticate with OAuth (see [Owner login and OAuth](#owner-login-and-oauth)) or, while `HH_MCP_LEGACY_TOKENS=true`, with long-lived legacy bearer tokens. Targets are listed in a file (their credentials can come from the vault). Do not expose `/mcp` or `/api` publicly; the public route is Stage 6.

**Targets.** List clusters in a TOML file and point `HH_TARGETS_FILE` at it:

```toml
[[proxmox]]
name = "home"                                   # your label; tools take it as `cluster`
endpoints = ["pve1.lab.example:8006"]           # reads use the first endpoint for now
tls = { kind = "ca_bundle", path = "/etc/harness/pve-home-ca.pem" }
# or: tls = { kind = "pinned", sha256 = "AB:CD:…" }   or: tls = { kind = "system" }

[proxmox.credentials.read]
token_id = "harness@pve!read"
token_secret = "secret://pve-home-read"            # a vault secret (see Vault), or:
# token_secret_file = "/run/secrets/pve-home-read" # only the secret; chmod 0400
```

Each credential sets exactly one of `token_secret` and `token_secret_file`.
- `token_secret` names a vault secret. It needs the vault (`HH_DATABASE_URL` and `HH_SECRETS_KEK_PROVIDER`), or startup refuses the file. The handle is resolved once at startup, after the database opens, and the use is audited as `secret.used` with consumer `targets:<capability>/<target>/<tier>`. The secret must exist and not be revoked, and must be a one-value kind (`proxmox_token`, `api_token`, `password`, …). For a `proxmox_token` its `token_id` must equal the file's. Any failure stops startup. After `hh secret rotate`, restart the harness to pick up the new version.
- Each secret file must not be readable by group or others, or startup refuses it. It is read once.

Either way, the value is registered with the redactor. `/readyz` gets one check per target, `proxmox:<name>`, which reports `degraded` (never `fail`) when the cluster cannot be read.

**Client tokens (legacy).** One token per client, so audit tells them apart and each can be revoked alone. `list` and `revoke` also show and revoke OAuth clients:

```bash
uv run homelab-harness-token create --client claude-code   # prints the token once, on stdout
uv run homelab-harness-token create --client claude-code --rotate   # new token; the old one stops working
uv run homelab-harness-token revoke --client claude-code
uv run homelab-harness-token list
```

Only a SHA-256 hash of each token is stored (`mcp_clients`). In the container, run it with `docker compose -f deploy/compose.yaml exec harness homelab-harness-token create --client claude-code`.

**Connecting.** See [clients.md](spec/clients.md#connecting-with-oauth-tailnet) for Claude Code and Codex. To check by hand:

```bash
curl -s -X POST localhost:8080/mcp -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2026-07-28' -H 'Mcp-Method: tools/list' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'
```

Every tool call writes an `mcp.tool_call` audit event (client, tool, target, outcome, duration; no arguments).

## Owner login and OAuth

The harness embeds a single-owner OAuth 2.1 authorization server (ADR-0007) for MCP clients. It needs `HH_DATABASE_URL` and `HH_PUBLIC_URL`. Passkeys work only in a secure context, so in dev use `http://localhost:<port>` (not `127.0.0.1`: WebAuthn refuses IP addresses as a relying party):

```bash
HH_ENV=dev HH_PUBLIC_URL=http://localhost:8080 uv run homelab-harness
uv run homelab-harness-owner enroll             # one-time link + 10 recovery codes, printed once
uv run homelab-harness-owner enroll --add-passkey
uv run homelab-harness-owner recovery-codes     # replace all codes
curl -s localhost:8080/.well-known/oauth-protected-resource/mcp
curl -s localhost:8080/.well-known/oauth-authorization-server
```

On the tailnet, terminate HTTPS in front of the harness (for example `tailscale serve --bg --https=443 http://127.0.0.1:8080`) and set `HH_PUBLIC_URL` to that `https://` origin. In the container: `docker compose -f deploy/compose.yaml exec harness homelab-harness-owner enroll`.

| Path | What |
|---|---|
| `/owner/login`, `/owner/enroll` | Server-rendered passkey pages (no inline script; strict CSP; `frame-ancestors 'none'`) |
| `/oauth/authorize`, `/oauth/consent` | Authorization request (PKCE `S256` required), then the owner's consent (session + CSRF; deny by default) |
| `/oauth/token`, `/oauth/revoke`, `/oauth/register` | Token exchange and refresh, RFC 7009 revocation, DCR for public clients |
| `/.well-known/oauth-authorization-server`, `/.well-known/oauth-protected-resource[/mcp]` | RFC 8414 and RFC 9728 metadata |

What is stored: only hashes of session, enrollment, code and token values (SHA-256; they are 256-bit random), scrypt hashes of recovery codes, and passkey public keys. Login, authorize, token and register are rate-limited in memory per client address and in total (`homelab_harness.auth.ratelimit`); the address is the one uvicorn reports (it honours `X-Forwarded-For` only from `127.0.0.1`), so behind a proxy that sends none, every request shares one address and the limits act as totals. With more than one worker process each enforces its own limits.

`hh clients list` and `hh clients revoke <id>` show and revoke OAuth clients and legacy tokens through `/api/clients`.

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
