"""Names of the harness's own metrics, as listed in observability.md (Signals).

Each instrument is created next to the code that produces it, using one of these
names, so the spec, the code and the Grafana dashboards agree on spelling. None
has a producer yet: tools, plans, approvals, jobs, adapters, inventory and events
arrive in later stages. Until then, HTTP traffic is measured by the FastAPI and
httpx instrumentation under the standard ``http.server.*`` and ``http.client.*``
names.
"""

from __future__ import annotations

TOOL_CALLS_TOTAL = "harness_tool_calls_total"
"""Counter: MCP tool calls, by ``tool``, ``client`` and ``outcome``."""

PLANS_TOTAL = "harness_plans_total"
"""Counter: plans created, by ``kind``, ``tier`` and ``decision``."""

APPROVAL_LATENCY_SECONDS = "harness_approval_latency_seconds"
"""Histogram: time from plan to owner decision."""

JOBS_TOTAL = "harness_jobs_total"
"""Counter: finished jobs, by ``kind`` and ``outcome``."""

JOB_DURATION_SECONDS = "harness_job_duration_seconds"
"""Histogram: job wall-clock duration."""

ADAPTER_REQUESTS_TOTAL = "harness_adapter_requests_total"
"""Counter: adapter calls to targets, by ``target`` and ``status_class``."""

ADAPTER_LATENCY_SECONDS = "harness_adapter_latency_seconds"
"""Histogram: adapter call latency."""

INVENTORY_AGE_SECONDS = "harness_inventory_age_seconds"
"""Gauge: seconds since the last successful inventory sync, by ``target``."""

EVENTS_TOTAL = "harness_events_total"
"""Counter: ingested events, by ``source`` and ``type``."""

ALL = (
    TOOL_CALLS_TOTAL,
    PLANS_TOTAL,
    APPROVAL_LATENCY_SECONDS,
    JOBS_TOTAL,
    JOB_DURATION_SECONDS,
    ADAPTER_REQUESTS_TOTAL,
    ADAPTER_LATENCY_SECONDS,
    INVENTORY_AGE_SECONDS,
    EVENTS_TOTAL,
)
"""Every name above, for the test that keeps them in step with the spec."""
