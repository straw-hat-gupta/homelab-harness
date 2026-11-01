# UI vision (post-v1)

> **Status: specification of future work.** It is **not part of v1**. In v1 the owner uses the `aa` CLI and ntfy on a phone. This document records the target, so v1 APIs don't block it. [roadmap.md](../roadmap.md) says what gets built when.

## What the UI is for

A single web workspace for the lab:
- terminals into any node, VM, LXC, or host, side by side;
- a dashboard the owner arranges from widgets;
- an approvals inbox;
- a chat panel that acts on the lab through the same plan → approve → apply path as every other client;
- live usage for the AI subscriptions the owner has connected.

## Stack

| Concern | Choice | Why |
|---|---|---|
| Framework | React 19, Vite, TanStack Router + Query | Server-side rendering isn't needed. A Python backend makes a Node server dead weight. Coding agents produce the most reliable React code. |
| Components | shadcn/ui, Tailwind 4 | Copy-in components, easy for an agent to modify |
| Shell and panels | **dockview** (8.x, zero dependencies) | VS Code–style splits, tabs, pop-outs, and side and top panels; layout serializes to JSON |
| Dashboard grid | **react-grid-layout** v2 (TypeScript rewrite) | Drag and resize grids inside a dockview panel |
| Terminals | **xterm.js 6** (`@xterm/xterm`) with `addon-fit`, `addon-webgl` (DOM fallback when the WebGL context is lost), `addon-search`, `addon-serialize`, `addon-unicode11` | The standard. 6.0 adds synchronized output. |
| Serving | Static build served by the FastAPI app, same origin as the REST API | One deployment unit, and no CORS |
| Auth | Owner session over the tailnet only. The UI is never published through the tunnel. | Shrinks the attack surface ([threat-model.md](threat-model.md)) |

Pin exact versions when scaffolding. The numbers above come from the 2026-10-31 research.

## Shell layout

```
┌ top panel: widget strip (node load · pool health · pending approvals · usage) ────┐
├ side panel ─┬ main area (dockview) ─────────────────────────────────────────────────┤
│ inventory   │ ┌ term: pve1 ──────┐ ┌ term: docker-01 ─┐ ┌ dashboard: "Home" ──────┐ │
│ tree        │ │ root@pve1:~#     │ │ $ docker ps      │ │ [grid of widgets]       │ │
│ approvals   │ │                  │ │                  │ │                         │ │
│ jobs        │ └──────────────────┘ └──────────────────┘ └─────────────────────────┘ │
│ chat        │ ┌ chat ───────────────────────────────────────────────────────────┐ │
│             │ │ plan p_7f3 preview · [open approval]                            │ │
└─────────────┴─┴─────────────────────────────────────────────────────────────────┴─┘
```

- The side and top panels are widget hosts, just like dashboard grids. The owner chooses what goes in them.
- Layouts (dockview JSON plus grid JSON) are stored per owner in the control plane, versioned. The agent can read and edit them through MCP tools: `ui.layout.get`, and `ui.layout.plan_update`, which is a T1 plan. That makes "add a disk-usage widget for pve2 to my top bar" work.

## Terminals

The browser never talks to Proxmox or SSH directly. The backend holds all credentials and proxies a WebSocket per pane.

| Target | Backend path |
|---|---|
| Proxmox node shell | `POST /nodes/{n}/termproxy`, then `GET /nodes/{n}/vncwebsocket?port&vncticket`. The first frame is `user:ticket\n`, followed by Proxmox's xterm framing (`0:len:data` input, `1:cols:rows` resize), ported from `pve-xtermjs`. |
| VM or LXC console | The same, under `/nodes/{n}/{qemu,lxc}/{id}/termproxy` |
| Linux or Docker host | `asyncssh` session as the owner's SSH identity. Prefer short-lived SSH certificates (OpenBao or step-ca) over static keys. |

Constraints:
- **Session tickets, not API tokens.** Tickets issued for API tokens are reportedly rejected at `vncwebsocket` (a forum report). A patch for token-owned tickets exists, but whether it has merged is unverified. Console access therefore uses a dedicated console-only Proxmox user (`VM.Console`, plus `Sys.Console` for node shells) whose short-lived session ticket the backend obtains. The browser never sees it.
- **Consoles bypass the plan model.** Opening a console is an owner action. It is audited as `console.opened` with target, user, and TTL, but no plan is needed when the owner opens it in the UI.
- **Agent-initiated sessions** are a T3 plan: target, user, TTL, and purpose. The agent **cannot type into a terminal the owner opened** unless the owner explicitly attaches it to that pane for a bounded time.
- **Recording.** The proxy records every session server-side as asciicast v2, so recording cannot be bypassed from the client. Recordings are retained per policy and linked from the audit log.
- Idle timeout, and a reconnect-and-resume of the pane layout.

## Dashboard and widgets

### Widget contract

A widget is **one file**, `ui/src/widgets/<id>.widget.tsx`:

```tsx
export const manifest = {
  id: "zfs-pool-health",
  title: "ZFS pool health",
  category: "storage",
  defaultSize: { w: 4, h: 3 },
  requires: ["proxmox:read"],               // capability scope the data source needs
} as const;

export const configSchema = z.object({     // auto-renders the settings form
  node: z.string(),
  pool: z.string().optional(),
  warnAtPercent: z.number().min(50).max(99).default(80),
});

export const dataSource = {                // always through the backend
  kind: "mcp-resource",                    // or "query" (REST endpoint)
  uri: (c: Config) => `lab://proxmox/${c.node}/zfs`,
  refreshSec: 30,
};

export function render({ data, config, size }: WidgetProps<Config, ZfsPools>) { … }
```

- Widgets are registered through `import.meta.glob("./widgets/*.widget.tsx")`, so a new file appears without any registry edit.
- The backend has a mirror **DataSource registry** in Python. Each data source is an MCP resource or a read-only REST query with its own scope check. Widgets never call providers.
- `configSchema` is exported as JSON Schema to the backend, so the agent can write valid widget configs.
- A contract test loads every widget, validates its manifest and schema, and renders it with fixture data. That is the coding agent's "done" check.
- **MCP Apps.** The same component can be bundled as an MCP App: a `ui://` resource, MIME `text/html;profile=mcp-app`, built with SDK `@modelcontextprotocol/ext-apps`. "Show me pool health on pve2" then renders the widget inside Claude, which supports MCP Apps on web and desktop. ChatGPT's support is reported as partial (unverified). Every MCP App response also carries a text fallback.

### Starter widgets

| Widget | Data source |
|---|---|
| Node load and memory | Proxmox RRD (`/nodes/{n}/rrddata`) or Prometheus |
| Disk and storage usage | `lab://proxmox/{node}/storage` |
| ZFS pool health | pool status, errors, scrub age |
| Disk wear and SMART | `/nodes/{n}/disks/list` wearout and health |
| Guest list | inventory guests with status, tags, and pool |
| Jobs and approvals queue | control-plane jobs and approvals |
| Backup age | latest successful backup per guest vs policy |
| Cloudflare tunnel status | tunnel connections, ingress list, Access coverage |
| Docker stacks | stack status and image digest drift |
| Tasks due | Obsidian Tasks due today or overdue |
| **Subscription usage** | see below |

## Approvals inbox

This is the same approval state machine as ntfy and the CLI ([safety-model.md](safety-model.md)). It adds:
- the full preview with diffs;
- the preflight results;
- the blast radius;
- a typed-confirmation field for T3 plans;
- a link to the job's live progress and its trace.

## Chat panel

The chat panel needs a model, and the harness doesn't run one. Options, to decide at UI time (an ADR will be needed):
1. **The owner's workstation CLI as the engine.** The UI talks to a small local bridge that drives the owner's own logged-in `claude` or `codex` CLI. Both are first-party binaries using the owner's own login on the owner's machine ([clients.md](clients.md)). The harness never touches the subscription credentials.
2. **API-key mode.** The owner supplies a model API key, and the backend runs a small agent loop against the harness's own MCP server.
3. **No embedded chat.** The UI deep-links into claude.ai or ChatGPT with the harness connector, and shows the resulting plans and jobs live.

Whichever option is chosen, the chat panel is just another MCP client. It gets no privileged path to apply.

## Live subscription usage

Show how much of each connected subscription the owner is using, live. Only official, client-emitted signals are used. **The harness never reads, copies, or polls with the owner's subscription tokens.**

| Source | Signal | How it reaches the harness |
|---|---|---|
| Claude Code statusline JSON | `rate_limits.five_hour` and `rate_limits.seven_day`: `used_percentage`, `resets_at`. Also `cost.total_cost_usd` (a client-side estimate) and `context_window.*`. | A statusline script installed by the steering plugin POSTs the JSON (without prompt content) to `POST /usage/claude-code` on the tailnet |
| Claude Code OpenTelemetry | `claude_code.token.usage`, `claude_code.cost.usage`, `claude_code.session.count`, and `claude_code.api_request` events | `CLAUDE_CODE_ENABLE_TELEMETRY=1`, OTLP exporters pointed at the harness's collector |
| Codex OTel | API, stream, and tool counters and histograms | `[otel]` in `~/.codex/config.toml` pointed at the collector |
| Codex rate limits | The app-server's `account/rateLimits/read` and `account/rateLimits/updated`: primary (5h) and secondary (weekly) `usedPercent`, `resetsAt` (the schema is marked unstable; unverified) | The bridge reads them from the owner's own Codex app-server session |
| claude.ai and ChatGPT web | Only the harness's own MCP tool-call log | Shown as **"tool calls only, quota unknown"** |

The widget shows a bar per subscription per window (5h, weekly), with reset countdowns, today's tokens and estimated cost, and the harness tool calls attributed to each client. Data lands in `usage_samples` ([observability.md](observability.md)), so Grafana can chart it too.

## How this differs from existing dashboards

| Project (late 2026) | Model | What we do differently |
|---|---|---|
| Homepage v2.7 | YAML services and widgets, 100+ built-in integrations, no auth | The agent writes and edits layouts. Widgets are data contracts, not hard-coded integrations. |
| Homarr v2.10 | Drag-and-drop boards, custom JSX widgets, an MCP server | Approvals, plans, durable jobs, and audit behind every action. Widgets double as MCP Apps. |
| Glance v0.8 | YAML pages, a generic `custom-api` widget | The data comes from the same typed inventory the agent reasons over |
| Grafana v13 | Dashboards as versioned JSON, Git Sync | Not trying to replace it. Grafana stays the deep-metrics tool, and our widgets can embed or link panels. |

The differentiator is not "has widgets" or "has MCP". It is that **every widget and every action share one typed model of the lab and one safety pipeline**, and the AI can author the UI itself.
