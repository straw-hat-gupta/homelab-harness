# Observability and honest reporting

> **Status: binding initial requirements; 1A has payload-free run/audit metadata and streamed terminal text only.** Full dashboards, distributed lab logs and subscription-usage ingestion are future decisions, not Stage 1 dependencies.

Record bounded lifecycle events for selected instance, session/native runtime ID, run start, tool name/target, authorization, duration, outcome, limits/cancellation and completion. Correlate IDs across the runtime adapter and tool service. Basic visibility must let the owner distinguish runtime failure, bad request, target error, partial data and interrupted work.

Audit these operations append-only with identifiers and counts. An audit failure refuses the tool result. Do not log prompts, responses, target bodies, command output, private notes, credential-bearing URLs or exception payloads. Redact registered secrets and encoded forms defensively. Native transcripts remain a separate private retained data store, not an excuse to log payloads.

Display tool progress honestly. A request submitted to the runtime is not completed work; a model completion is not verified target success. Mark unknown effects uncertain for future writes. If cancellation was requested but termination cannot be confirmed, report that uncertainty and keep independent tool deadlines in force.

Expose current process/connection readiness and safe setup diagnostics appropriate to the increment. Do not invent working `hh doctor`, telemetry exporters or route names before implementation. Readiness must distinguish unavailable targets from missing credentials and from a failed service dependency.

Capture available runtime-reported usage per run/version. Unknown is unknown; list-price estimates are not bills and wrapper tool-call counts are not total model tokens. Choose numerical budgets and reporting fields in the 1A proof rather than asserting unmeasured savings.

Existing OpenTelemetry/redaction/audit code is a reuse candidate. Postgres, Grafana, Prometheus, Tempo, Loki, collectors, alert services and usage widgets are not automatically part of the minimal installation. Revisit when a real debugging task justifies them.
