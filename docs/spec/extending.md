# Extending the harness

> **Status: specification.** This is the contract that makes "ask my coding agent to add X" work. The template, test kit and skill named here are built in Stage 1 (see the [roadmap](../roadmap.md)).

## The one rule

**A new capability is a new package under `capabilities/`. You don't edit `core`.** If a capability seems to need a core change, that change is a separate PR that extends the SDK for every capability, with its own ADR when it touches safety.

## What a capability provides

```
capabilities/<name>/
  manifest.toml        # name, version, targets it manages, credential tiers + required scopes,
                       # tool list with tiers, min target versions
  adapter.py           # typed external calls; timeouts; maps errors to sdk.errors.*; no DB, no policy
  models.py            # pydantic types for the domain (inputs, inventory rows, plan parameters)
  tools.py             # @read_tool and @plan_tool functions (MCP surface)
  planners.py          # build Plan: preflight checks, observed facts, preview, steps, rollback
  executors.py         # @step functions run by core jobs; each declares retry class
  inventory.py         # optional: sync function → typed rows + as_of
  resources.py         # optional: MCP resources
  steering/            # skills + runbooks for this domain (built into the pack)
  tests/
    fixtures/          # recorded responses (scrubbed)
    test_contract.py   # one line: runs the shared contract kit against this capability
    test_planners.py   # preflight/preview cases incl. refusals
    test_executors.py  # success, each error class, ambiguity → uncertain
evals/<name>/          # golden transcripts + injection cases for this domain
```

## The SDK surface (planned, illustrative)

```python
from homelab_harness_sdk import read_tool, plan_tool, step, Preflight, Preview, RetryClass, Tier

@read_tool(credential="read")
async def list_pools(ctx, node: str) -> list[ZfsPool]: ...

@plan_tool(kind="truenas.dataset.create", default_tier=Tier.T2, credential="write")
async def plan_dataset(ctx, pool: str, name: str, quota_gb: int | None = None) -> PlanDraft:
    live = await ctx.adapter.get_pool(pool)
    return PlanDraft(
        parameters=DatasetCreate(pool=pool, name=name, quota_gb=quota_gb),
        observed={"pool_guid": live.guid},
        preflight=[Preflight.check("pool healthy", live.health == "ONLINE", evidence=live.health)],
        preview=Preview.create(f"{pool}/{name}", fields={"quota": quota_gb or "none"}),
        steps=["create_dataset"],
        rollback="destroy dataset (harness can do this; data written since is lost)",
    )

@step(retry=RetryClass.IDEMPOTENT)          # safe to repeat: create-if-absent
async def create_dataset(ctx, p: DatasetCreate) -> StepResult: ...
```

Core turns these into MCP tools with JSON Schemas, assigns tiers through policy, stores plans, runs approvals and jobs, and emits telemetry and audit records. The capability never sees an approval and never decides a tier, though it may *suggest* one.

## The contract test kit (applies to every capability automatically)

| Check | Fails when |
|---|---|
| Schemas | A tool's input or output schema isn't valid JSON Schema, or the docstring or description is empty |
| Classification | A tool is neither `@read_tool` nor `@plan_tool`, or an adapter write method is reachable from a tool |
| Tiers | A plan kind matching a safety floor pattern declares a lower default tier |
| Retry classes | An executor step has no retry class, or an `unsafe` step is retried in the recovery test |
| Error mapping | Fixture-driven 401, 403, 404, 409/lock, 429, 5xx and timeout don't map to the shared error types |
| Redaction | The canary secret or body shows up in logs, spans, previews, errors or audit |
| Credentials | A tool uses a credential tier that the manifest doesn't declare |
| Preview | A plan has no rollback note, no preview diff, or no observed facts for the re-preflight |
| Steering | A tool has no mention in at least one skill or runbook (keeps steering in sync) |

## The coding-agent workflow

The repo ships a skill, `steering/dev/new-capability/SKILL.md`, which is exposed to Claude Code and Codex. It walks the agent through these steps:
1. Copy `capabilities/_template`, rename it, and fill in `manifest.toml`.
2. Write the adapter against the target's API docs, then record and scrub fixtures.
3. Add read tools first, run the contract kit, and open a PR (useful on its own).
4. Add plan tools: preflight, preview, steps and rollback, plus planner tests that include refusals.
5. Add executors with retry classes and executor tests, including the ambiguity case.
6. Write steering: one skill and one runbook. Add an eval case and an injection case.
7. Update `docs/spec/capabilities/<name>.md` and the CHANGELOG.

## Example extensions (designed for, not in v1)

| Capability | Notes |
|---|---|
| `pbs` | Proxmox Backup Server: datastore usage, verify jobs, restore drills. Same API shape as PVE. |
| `knowledge` (the "RAG server") | Indexes the Obsidian vault, runbooks and lab docs. With no local models and no embedding API, it starts with Postgres full-text search (BM25-style ranking) plus *agentic retrieval*: it exposes `search`, `read`, `outline` tools and lets the client model iterate. If an embedding API key is added later, hybrid search with pgvector is a drop-in addition behind the same tools. |
| `truenas`, `unifi`, `home_assistant` | Home Assistant already ships an MCP server. A thin capability can proxy it through the harness's policy and audit, or the owner connects it directly to clients for non-infra use. |
| `opentofu` | Declarative backend for fleet changes. `tofu plan -detailed-exitcode` output becomes the preview, and `apply` the executor. |
