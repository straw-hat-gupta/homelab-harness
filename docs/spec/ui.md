# Web UI: an AI-native replacement for the Proxmox GUI

> **Status: UI-1 foundation implemented** (the app shell, the registries below, the side tree, object pages with Summary and a placeholder Tasks tab, the `stat`, `table`, `status-list`, `markdown` and `log-tail` templates, ⌘K search, the theme switch, and serving by FastAPI). Its data comes from an **interim read façade** (`GET /api/ui/tree`, `GET /api/ui/objects/{type}/{id}/summary`) over the Proxmox read tools; the lab state replaces it in Stage 2. Not yet built: Logs, SSE live updates, passkey login (an owner token is asked for meanwhile), and everything from UI-2 on. How to extend it: [ui/README.md](../../ui/README.md). The UI is part of v1, starts small and grows in planned increments (below). It is designed from the first version so that adding functionality means **registering an extension**, not rewriting pages. This document replaces the earlier "UI vision (post-v1)".

## Goals

1. **Replace the Proxmox web UI for daily use**, with the same mental model: a datacenter → nodes → guests and storage tree, and per-object pages.
2. **AI wired into every view:**
   - a context-aware assistant panel;
   - every action is a plan with a preview;
   - lab documents and logs are one click away;
   - agents can extend the UI using the catalog.
3. **Simple first, extensible by design.** Version 1 of the UI is a read-only navigator plus a few pages. Every later feature plugs into the extension points defined here.

## Stack

| Concern | Choice | Why |
|---|---|---|
| Framework | React 19, Vite, TypeScript strict, TanStack Router (file routes) + TanStack Query | No SSR is needed with a Python backend. Typed routing and data caching. Coding agents produce reliable React. |
| Components | shadcn/ui + Tailwind 4 | Components are copied in and owned by the repo, easy for agents to modify, and give one consistent design system |
| API types | `openapi-typescript`, generated from FastAPI's OpenAPI spec | One source of types. Widget configs are checked against data-source shapes. |
| Live updates | Server-Sent Events from `/api/events` (lab changes, job progress, approvals) | Simpler than WebSockets for one-way updates. WebSockets are used only for terminals. |
| Panels (UI-3+) | dockview | VS Code-style splits and tabs, with layouts serialized to JSON |
| Dashboard grid (UI-2+) | react-grid-layout v2 | Drag and resize |
| Terminals (UI-4) | xterm.js 6 through a backend WebSocket proxy | See [Terminals](#terminals) |
| Serving | A static build served by FastAPI on the same origin. Tailnet only, owner passkey session. | One deploy unit, no CORS, never public |
| Tests | Vitest + Testing Library (components and templates), Playwright (a smoke test per route against a fixture lab state) | |

## Layout

```
┌ top bar: search (⌘K: objects, recipes, docs) · pinned widgets · approvals badge · usage ┐
├ side nav (tree) ─┬ object page ──────────────────────────────────────┬ assistant (UI-3) ┤
│ ▾ Datacenter     │ pve2 · node                                       │ context: pve2   │
│   ▾ pve1         │ [Summary] [Guests] [Storage] [Network] [Tasks]    │ "why is load    │
│     100 dns      │ [Logs] [ZFS]                                      │  high?"         │
│     112 grafana  │  ┌ cpu ─┐ ┌ mem ─┐ ┌ zfs health ───────┐          │ → reads lab://… │
│   ▸ pve2         │  └──────┘ └──────┘ └───────────────────┘          │ → plan preview  │
│ ▸ Storage        │  recent tasks …   alerts …                        │                 │
│ ▸ Services       │                                                   │                 │
│ ▸ Cloudflare     │ actions: [Start] [Shutdown] [Snapshot] [Migrate…] │                 │
└──────────────────┴───────────────────────────────────────────────────┴─────────────────┘
```

## Extension points (designed in from UI-1)

Everything visible is contributed through a registry. Core pages use the same registries as extensions do, so there is one way to add things.

| Registry | What gets registered | Example | Where |
|---|---|---|---|
| **Object types** | An entity kind with an icon, a tree placement, a route and a lab-state data source | `node`, `qemu`, `lxc`, `storage`, `zfs-pool`, `stack`, `tunnel` | `ui/src/objects/<type>.object.ts` |
| **Object tabs** | A tab on an object page, for given object types, built from widgets and sections | "ZFS" tab on `node`; "Backups" tab on `qemu` and `lxc` | `ui/src/tabs/<id>.tab.tsx` |
| **Actions** | A button or menu item bound to a **recipe**. The UI renders its form from the recipe's input schema, prefilled from the object, and opens the plan preview. | "Snapshot" on guests → `proxmox.guest.snapshot` | `ui/src/actions/<id>.action.ts`, usually generated from recipe metadata |
| **Routes** | Top-level pages | `/services`, `/cloudflare`, `/audit` | TanStack file routes |
| **Widget templates and widgets** | See [catalog.md](catalog.md) | `status-list` + `zfs.pool_health` | `ui/src/templates/`; widgets are configs |
| **Command palette entries** | Searchable commands | "Open pve2 logs", "Run recipe…" | Derived from objects, actions and recipes |

Rules:
- **Registration is automatic.** Files are discovered with `import.meta.glob`, so adding a capability's UI never edits a central list.
- **Actions are generated from recipes.** A new recipe whose metadata includes `ui: {object_types: [...], label, icon}` appears as an action on those objects with no UI code. The form comes from the recipe's typed inputs, and the confirmation is the harness plan preview, the same as ntfy and the CLI. A hand-written action is needed only for a custom form.
- **Tabs and pages are composed of widgets and sections**, not bespoke markup: lab-document sections, data-source tables and log tails. A new tab is mostly configuration.
- **Each registry has a contract test** covering the manifest schema, the data-source scope, rendering with a fixture lab state, and accessibility.

## Increments

| Increment | Roadmap stage | Scope |
|---|---|---|
| **UI-1: navigator (read-only)** | Stage 2 | App shell, the side tree (datacenter, nodes, guests, storage), object pages with a Summary tab (lab-document sections plus a few `stat` and `table` widgets), Tasks and Logs tabs (data sources over task history and Loki), search, live updates over SSE, passkey login. **No actions.** |
| **UI-2: dashboards and widgets** | Stage 2 | Widget templates (`stat`, `gauge`, `timeseries`, `table`, `status-list`, `log-tail`, `markdown`), the home dashboard (react-grid-layout), pinnable top-bar widgets, layout storage, and `ui.layout.plan_update` so agents can add widgets |
| **UI-3: actions, approvals, assistant** | Stage 3 | Actions generated from recipes, plan preview and approval inbox (typed confirm for T3), job progress, the context-aware assistant panel ([Assistant](#assistant-panel)), and dockview panels |
| **UI-4: terminals and consoles** | Stage 4 | Multi-pane terminals: node shells, VM and LXC consoles, SSH hosts |
| **UI-5: ecosystem pages** | Stages 5–6 | Services, Cloudflare (tunnels, DNS, Access coverage), stacks, tasks (Obsidian), the subscription usage widget, the audit explorer |

Each increment ships with Playwright smoke tests and adds no new framework.

## Assistant panel

- A context-aware chat docked on the right. It knows the current object, tab and selection, so "why is load high?" on `pve2` already carries `{object: node/pve2}`.
- **It needs a model, and the harness runs none** ([clients.md](clients.md)). The options, decided in an ADR at UI-3:
  1. **Bridge to the owner's own CLI.** A small workstation bridge drives the owner's logged-in `claude` or `codex` (first-party binaries, the owner's own login).
  2. **API-key mode**, run against the harness's own MCP server.
  3. **Deep links** into claude.ai or ChatGPT with the harness connector and context, with the resulting plans and jobs shown live.
- The assistant is a normal MCP client. It reads lab documents, data sources and logs, and proposes recipes. It has **no privileged path**: actions still need approval.

## Terminals

- The browser never talks to Proxmox or SSH directly. The backend proxies a WebSocket for each pane.
- **Proxmox node shell and VM/LXC consoles:** `termproxy`, then `vncwebsocket`, using a console-only user's short-lived session ticket. API-token tickets are reportedly rejected (unverified).
- **Linux hosts:** asyncssh, using `ssh-sign` brokered keys ([secrets.md](secrets.md)).
- **Audit and recording:** sessions are recorded server-side as asciicast v2, and `console.opened` is audited.
- **Agent sessions:** an agent-initiated session is a T3 plan. An agent can never type into a terminal the owner opened unless the owner attaches it for a bounded time.

## Live subscription usage (UI-5)

Unchanged from the earlier design:
- **Claude Code:** statusline `rate_limits` (5-hour and 7-day `used_percentage`, `resets_at`), plus Claude Code OTel token and cost metrics.
- **Codex:** OTel and app-server rate-limit events (unverified).
- **claude.ai and ChatGPT:** labelled "tool calls only, quota unknown".

The harness never reads or polls with subscription tokens. See [clients.md](clients.md#usage-visibility) and [observability.md](observability.md#client-usage).

## How this differs

| Tool | What we add |
|---|---|
| The Proxmox web UI | The same navigation, plus lab documents, cross-node views (services, storage, exposure), recipes with previews and approvals, logs in context, an AI assistant, and agent-authored widgets |
| Homepage, Homarr, Glance | Not a link dashboard. It's an operations console with a typed lab model and a safety pipeline behind every action. |
| Grafana | Stays the deep-metrics tool. The UI embeds or links its panels instead of re-implementing them. |
