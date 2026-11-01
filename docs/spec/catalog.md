# Catalog: data sources, widget templates and reuse

> **Status: specification.** Nothing here is implemented yet. The catalog is what lets an agent extend the harness without producing slop: it knows what already exists and composes it. Terms follow the [glossary](../../GLOSSARY.md).

## The rule: reuse before create

Before adding a recipe, data source, widget, step, doc or helper, an agent (or a human) **searches the catalog**. It extends or composes what exists, and creates something new only when nothing fits. That new thing must itself be reusable. This rule appears in AGENTS.md, in the steering pack, and in CI checks.

## What the catalog holds

| Kind | What it is | Example | Defined in |
|---|---|---|---|
| **Data source** | A typed, read-only, scoped query: parameters in, typed rows or series out | `node.load(node)`, `zfs.pool_health(node?)`, `guests.list(filter)`, `storage.usage()`, `backups.age(policy)`, `logs.tail(target, unit)`, `tunnels.status()` | Python, in core or a capability (`@data_source`) |
| **Widget template** | A UI component that renders a *shape* of data, not a specific source | `stat`, `gauge`, `timeseries`, `table`, `status-list`, `log-tail`, `bar`, `markdown` | TypeScript, in `ui/src/templates/` |
| **Widget** | A config: template, data source, parameters, display options | `{template: "status-list", source: "zfs.pool_health", params: {node: "pve2"}, options: {warnAt: 80}}` | JSON, stored in the layout, with no code |
| **Recipe** | A tested operation ([recipes.md](recipes.md)) | `storage.zfs.create_pool` | Python or YAML |
| **Step** | A low-level executor step shared by recipes | `proxmox.task.wait` | Python |
| **Lab document** | A rendered view of the lab state ([lab-state.md](lab-state.md)) | `lab://storage` | Python renderer |
| **Reference doc** | Curated Proxmox, ZFS, Cloudflare or Docker knowledge | `docs://zfs/layouts` | Markdown |
| **UI extension** | A route, object-page tab, or action contributed to the UI ([ui.md](ui.md#extension-points)) | a "ZFS" tab on node pages | TypeScript plus a manifest |

## Data sources

```python
@data_source(
    id="zfs.pool_health",
    summary="Health, capacity, fragmentation and last scrub for ZFS pools",
    params=ZfsPoolHealthParams,          # node: NodeRef | None
    returns=list[ZfsPoolHealthRow],      # shape: "rows" → fits table, status-list
    shape="rows",
    freshness="lab_state",               # or "live" (calls target), "metrics" (Prometheus), "logs" (Loki)
    scope="proxmox:read",
    budget_tokens=600,
)
async def zfs_pool_health(ctx, p: ZfsPoolHealthParams) -> list[ZfsPoolHealthRow]: ...
```

- **One definition, three consumers.** Each data source is served at:
  - REST, `GET /api/data/{id}`, for the UI;
  - an MCP resource, `data://{id}?…`, for agents;
  - CLI, `hh data {id}`.
- **Shapes** connect sources to templates: `scalar`, `rows`, `series`, `log-lines`, `markdown`. The catalog lists which templates accept which shape.
- **Freshness classes:**
  - `lab_state` sources read the lab-state DB, so they are cheap and include `as_of`.
  - `metrics` sources query Prometheus.
  - `logs` sources query Loki.
  - `live` sources call the target, and are used sparingly.
- **Typed end to end.** FastAPI's OpenAPI spec produces TypeScript types (`openapi-typescript`), so a widget config is checked against its source's return shape at build time and at save time.

## Widget templates

A template is one file in `ui/src/templates/<name>.template.tsx`:

```tsx
export const template = defineTemplate({
  name: "status-list",
  accepts: ["rows"],                         // data shapes
  options: z.object({                         // auto-renders the settings form
    labelField: z.string(),
    statusField: z.string(),
    warnAt: z.number().optional(),
  }),
  render: ({ rows, options, size }) => <StatusList … />,
});
```

- Templates are generic, and know nothing about Proxmox. A new widget is almost always **a config** that combines an existing template with an existing or new data source.
- Write a new template only for a genuinely new *visual shape*, for example a topology diagram.
- Templates are registered automatically through `import.meta.glob`.
- Each template has a contract test: it renders every accepted shape from fixtures and is checked for accessibility.

## How an agent adds a widget

1. `catalog.search("zfs health")` finds the `zfs.pool_health` data source and the `status-list` and `table` templates.
2. If the data needed isn't there, the agent adds **one data source**, following the rules below, ideally by composing existing lab-state queries.
3. The agent writes the widget config and submits it with `ui.layout.plan_update`. That's a T1 plan: the preview shows the config diff and a rendered thumbnail.
4. There is no new HTML or CSS unless a new template is truly needed.

## Anti-bloat checks (CI)

| Check | Fails when |
|---|---|
| Duplicate data source | Two sources have the same params and return types and overlapping summaries. Name similarity plus a schema hash flags it for review. |
| Unused things | A data source, template, step or helper has no consumer for two releases. The check warns first, then fails. |
| Template sprawl | A new template's accepted shapes and options duplicate an existing template's |
| Budget | A data source's sample output exceeds `budget_tokens` |
| Catalog completeness | Something exists in code but isn't in the catalog, or the reverse |

## Catalog API

- `catalog.search(query, kinds?)` and `catalog.describe(id)` are T0 MCP tools, also available as REST and as `hh catalog`.
- Search uses Postgres full-text search over ids, summaries, tags and examples. It's deterministic and needs no embeddings.
- `catalog://index` is a compact resource listing everything by kind (≤ 2k tokens, paginated). Agents read it at the start of extension work.
