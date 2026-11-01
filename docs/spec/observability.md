# Observability

> **Status: specification.** It describes what the harness will emit and how the owner will see it.

## Goals

1. Every client request can be followed end to end. A single trace covers the MCP tool call, then the plan, the approval wait, the job steps, the external task (UPID) and verification.
2. The owner can answer "what did the AI do in my lab this week?" from Grafana or the CLI in under a minute.
3. Nothing sensitive is emitted: no tokens, note bodies or command output at INFO, and no secrets ever.
4. Usage per AI client is visible live (see [Client usage](#client-usage)).

## Signals

| Signal | Tool | What's emitted |
|---|---|---|
| Traces | OpenTelemetry SDK, OTLP to the Collector, then Tempo | Spans for every MCP request (`mcp.tool`), planner (`plan.create`), policy decision, approval wait (span link, not a long span), each job step, each adapter call (`proxmox.http`, `ssh.exec`, `cloudflare.http`, `github.http`), and verification |
| Metrics | OTel metrics, then Prometheus | `harness_tool_calls_total{tool,client,outcome}`, `harness_plans_total{kind,tier,decision}`, `harness_approval_latency_seconds`, `harness_jobs_total{kind,outcome}`, `harness_job_duration_seconds`, `harness_adapter_requests_total{target,status_class}`, `harness_adapter_latency_seconds`, `harness_inventory_age_seconds{target}`, `harness_events_total{source,type}` |
| Logs | structlog JSON to stdout, then Loki | One event per state transition, keyed by `plan_id`, `job_id`, `upid`, `client_id` and `trace_id`, with no payloads |
| Audit | Postgres `audit_events` (append-only) | The legal record of what happened. Queryable with `aa audit` and a Grafana Postgres datasource. |

**Semantic conventions.** Use OTel's HTTP, DB and RPC conventions where they apply. The GenAI conventions are still in development and the harness makes no model calls, so MCP spans use attributes in the `mcp.*` and `harness.*` namespaces, documented in `docs/telemetry-attributes.md` (to be written with the code).

## Redaction

- A structlog processor and an OTel span processor drop or mask keys matching the secret patterns (`token`, `secret`, `password`, `authorization`, `ticket`, `cookie`, `PVEAPIToken`, `ssh-…`). They also mask any value matching a vault-registered secret.
- Target-sourced text (descriptions, logs, note bodies, command output) is never put in span attributes or logs. Only lengths and hashes are recorded.
- The contract test kit plants a canary secret and a canary body in fixtures for every capability. It asserts that neither appears in captured logs, spans, previews, error responses or audit rows.

## Dashboards (shipped in `deploy/grafana/`)

1. **Harness overview:** tool calls by client, plans by tier and decision, the pending-approvals count, job outcomes (with `uncertain` highlighted), adapter error rates, inventory freshness.
2. **Job explorer:** a table of recent jobs linking to Tempo traces and Proxmox task logs.
3. **Client usage:** see below.
4. **Lab health:** node CPU, memory and disk, ZFS pool state, backup age per guest, and tunnel status, from inventory plus Proxmox RRD or Prometheus node metrics.

## Alerts (to ntfy)

- A job ended `uncertain` or `failed`.
- An approval is pending for more than 10 minutes on a plan the owner started, as a reminder.
- Inventory has been stale for more than 5 minutes for a target, meaning the target is unreachable or the token has expired.
- A capability token expires within 7 days.
- A Proxmox event matches the alert matchers: backup failure, a degraded ZFS pool, a SMART warning, a node going offline.

## Client usage

The owner wants to see live usage for each AI subscription while working. The sources that are actually available are listed in [clients.md](clients.md#usage-visibility). The design:

```
Claude Code ──statusline script (POST rate_limits JSON)──► harness /usage/claude-code   (tailnet)
Claude Code ──OTLP metrics/events──────────────────────► otel-collector ─► Prometheus
Codex CLI   ──OTLP + rate-limit events (runner)────────► otel-collector / harness /usage/codex
all clients ──MCP calls──► harness audit (per client_id)
```

- `usage_samples` stores the latest rate-limit snapshot per client and window, as used percentage plus `resets_at`. Token and cost counters stay in Prometheus.
- `aa usage` shows a live table: client, 5-hour window percentage, reset time, weekly percentage, today's tokens and estimated cost, and today's harness tool calls. The UI widget comes after v1 ([ui-vision.md](ui-vision.md)).
- Web clients (claude.ai, ChatGPT) show harness tool calls only, labelled "quota not reported by vendor".
- Cost figures from Claude Code are list-price estimates. Label them that way; they are not bills.

## Health and readiness

- `/healthz`: the process is up.
- `/readyz`: the DB is reachable, DBOS is initialized, the vault key is loaded, and each target's last sync is under 5 minutes old. A degraded target makes the probe report `degraded` rather than fail.
- `aa doctor`: an end-to-end check covering token scopes against expected privileges, TLS pins, tunnel route allowlist, ntfy delivery, and OTel export.
