# ADR-0010: Lab state, recipes and a reuse-first catalog, with token efficiency as the goal

- **Status:** accepted (2026-11-01)

## Context

The owner already runs Codex and Claude on lab nodes, and they can perform the same operations through a shell. What makes the harness worth having is doing that work **with far fewer tokens and far less guessing**:
- no discovery on every session;
- no improvised commands;
- attributable failures;
- a UI that replaces the Proxmox web UI.

The owner also wants extensions (widgets, scripts) to reuse existing parts instead of piling up one-off code. And it must be easy to adopt the harness on an existing lab.

## Decision

1. **Lab state.** Deterministic sync code keeps one typed model of the lab and renders budgeted **lab documents** (`lab://…`). Node, task and container logs are centralized in Loki behind `logs.query`. An optional Git mirror records the lab's change history. See [lab-state.md](../spec/lab-state.md).
2. **Recipes.** Common operations are tested, versioned, typed, composable and lab-agnostic recipes, either Python recipes or YAML script recipes with argv templates. Recipes are the plan tools. Raw commands are T3, and get promoted into recipes. See [recipes.md](../spec/recipes.md).
3. **Catalog.** Data sources, widget templates, recipes, steps and docs are indexed and searchable. CI checks for duplicate and unused entries. Widgets are configs over templates plus data sources. See [catalog.md](../spec/catalog.md).
4. **Failure attribution.** Every job failure is classified as agent, recipe, target or uncertain ([observability.md](../spec/observability.md#failure-attribution)).
5. **Adoption.** `hh init` adopts an existing lab read-only and infers a lab profile that recipes use for defaults ([onboarding.md](../spec/onboarding.md)).
6. **Token efficiency is measured.** The harness is compared against a plain-agent baseline ([testing-and-evals.md](../spec/testing-and-evals.md#token-efficiency)).

## Consequences

- More deterministic code to write and maintain (sync, renderers, recipes), but that is exactly the part that can be tested.
- The UI moves into v1 ([ADR-0011](0011-web-ui-stack.md)), because it is the owner's main interface.
- Agents need clear steering to read the lab state first and to use recipes ([steering.md](../spec/steering.md)).
