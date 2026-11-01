# ADR-0008: OpenTelemetry into Prometheus, Tempo, Loki and Grafana; no LLM-observability product

- **Status:** accepted (2026-10-31)

## Context

The earlier plan proposed Langfuse for LLM tracing. Under ADR-0003, the harness makes no model calls, so prompt and completion tracing has nothing to trace. What needs observing is tool calls, plans, approvals, jobs and adapter calls, plus client usage telemetry, which Claude Code and Codex already emit over OTLP. Grafana's stack is the home-lab standard, and recruiters know it.

## Decision

- Instrument with the OpenTelemetry SDK.
- Run an OTel Collector that receives from the harness and from the clients' OTLP exporters.
- Send metrics to Prometheus, traces to Tempo and logs to Loki, all viewed in Grafana. Dashboards are versioned in `deploy/grafana/`.
- If the lab already has a stack, the collector exports to it instead.

Details are in [observability.md](../spec/observability.md).

## Consequences

- One observability story covers both the harness and the clients' usage.
- If API-key mode ([ADR-0003](0003-mcp-first-bring-your-own-ai.md)) adds model calls later, Langfuse or OTel GenAI spans can be added then.
