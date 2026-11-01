# ADR-0011: Web UI in v1, React + Vite + TanStack + shadcn/ui, extensible through registries

- **Status:** accepted (2026-11-01). It supersedes the "no web UI in v1" non-goal.

## Context

The owner wants the harness to replace the Proxmox web UI. They also want it to start simple and grow, with extending it built into the design.

## Decision

- **Stack:** React 19, Vite, strict TypeScript, TanStack Router and Query, shadcn/ui with Tailwind 4, and SSE for live updates. API types are generated from FastAPI's OpenAPI spec. The build is static and served by FastAPI on the tailnet.
- **Built in increments:**
  - UI-1, a read-only navigator;
  - UI-2, widgets and dashboards;
  - UI-3, actions, approvals and the assistant;
  - UI-4, terminals;
  - UI-5, ecosystem pages.
- **Registries from day one:** object types, object tabs, actions (generated from recipes), routes, widget templates and the command palette. Files are discovered automatically. Core pages use the same registries as extensions.

Details are in [ui.md](../spec/ui.md).

## Alternatives

- **Next.js:** SSR and a Node server aren't needed with a Python backend.
- **HTMX with server templates:** simpler at first, but weaker for terminals, dashboards and typed widget composition. Coding agents also produce less reliable results with it.
- **SvelteKit:** fine technically, but there is less agent fluency and a smaller component ecosystem.

## Consequences

- A TypeScript toolchain joins CI: lint, typecheck, Vitest, Playwright smoke tests, and the build.
- The UI depends on stable REST, data-source and SSE contracts. These are versioned, and checked in CI through the generated types.
