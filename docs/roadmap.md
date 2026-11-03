# Roadmap

This file covers what gets built, in what order, and how we know each stage is done. Every stage ends in something the owner uses. Each stage is a handful of PRs, and each PR has one concern. Effort is in focused days and is rough.

The spec is in [`docs/spec/`](spec/README.md), the decisions are in [`docs/adr/`](adr/), and the vocabulary is in [GLOSSARY.md](../GLOSSARY.md). The goal set by [ADR-0010](adr/0010-lab-state-recipes-token-efficiency.md) is the same work as a plain agent with a shell, but with far fewer tokens. The UI that replaces the Proxmox web UI is part of v1 ([ADR-0011](adr/0011-web-ui-stack.md)).

## Stage 0: Specification ✅

- [x] Archive v0, and write the spec, ADRs 0001–0009 and the glossary. Resolve D-1 and D-2.
- [x] Re-scope to lab state, recipes, the catalog, the UI in v1, and onboarding (ADR-0010 and ADR-0011, 2026-11-01).

## Stage 1: Foundation, read-only Proxmox, MCP (in progress)

| Item | Status |
|---|---|
| Skeleton: uv workspace, core app, settings, redaction, logging, `hh`, CI, image (#19) | ✅ |
| Postgres, Alembic, DBOS, append-only audit (#20) | ✅ |
| Proxmox read-only adapter, TLS pinning, bootstrap script (#24) | ✅ |
| Vault crypto: envelope encryption, KEK providers, secret kinds (#22) | ✅ |
| Observability: OTel, plus Prometheus, Tempo, Loki and Grafana (#23) | ✅ |
| MCP server with Proxmox read tools, interim owner tokens, audit per call, contract kit | in progress |
| Vault persistence and the `hh secret` and `hh vault` CLI (#28) | ✅ |
| Owner OAuth: embedded authorization server, passkey login, `hh clients` ([ADR-0007](adr/0007-owner-auth.md)) | in review (live client logins unverified; CLI device flow is a follow-up) |

**Done when:**
- Claude Code and Codex connect over the tailnet and answer read questions about the cluster.
- The trace is visible in Grafana.
- `hh doctor` is green.

## Stage 2: Lab state, logs, onboarding, and UI-1 and UI-2 (≈ 7–9 days)

Daily value: open the harness UI instead of the Proxmox UI to look at the lab. Agents read the lab documents instead of running discovery.

**Lab state** ([lab-state.md](spec/lab-state.md))
- Entities, sync workflows, change events and SSE.
- Renderers for `lab://overview`, `nodes`, `guests`, `storage`, `network`, `backups` and `services`, with budgets.
- `hh lab show`, plus the optional Git mirror.

**Logs**
- Loki ingestion of Proxmox task logs.
- A node collector recipe (Alloy) for journald.
- `logs.query` and `logs.around`, with dedup and budget.

**Catalog** ([catalog.md](spec/catalog.md))
- `@data_source` and the starter data sources.
- `catalog.search` and `catalog.describe`, plus `catalog://index`.
- The anti-bloat CI checks.

**Onboarding** ([onboarding.md](spec/onboarding.md))
- `hh init`: endpoint, TLS pin, identity script, discovery, inferred lab profile, `hh doctor`.
- Profile inference tests across lab shapes.

**UI-1 and UI-2** ([ui.md](spec/ui.md))
- **Shell:** the app shell with its registries (objects, tabs, routes, templates); the side tree; object pages for Summary, Tasks and Logs; search; SSE; passkey login.
- **Widgets:** the widget templates, the home dashboard and top-bar widgets, and `ui.layout.plan_update`.

**Done when:**
- On the owner's existing cluster, `hh init` completes with no lab changes beyond the harness identity, and the UI shows every node and guest.
- "What's eating disk on pve2" is answered from `lab://` documents with no shell.
- Token budgets are enforced in CI.

## Stage 3: Plans, approvals, jobs, recipes, and UI-3 (≈ 6–8 days)

Daily value: operate guests from the UI or from chat, with approvals on the phone.

**Core**
- The plan model, hashing, preview renderer, and the policy engine (tiers, floors).
- Approvals with ntfy (ADR-0006) and `hh approve`.
- DBOS jobs: re-preflight, retry classes, UPID polling, verification, outcomes, and failure attribution.

**Recipes** ([recipes.md](spec/recipes.md))
- The `@recipe` SDK, ref resolution against the lab state, composition, `recipes.search` and `describe`, and the script-recipe runner.
- The guest recipe set.

**UI-3**
- Actions generated from recipes, the approvals inbox, job progress, and the assistant panel (decided by ADR at the start of the stage).

**Done when:**
- "Make me a VM" works from chat and from a UI button.
- Destroy requires typed confirmation.
- Tests pass for crash recovery, approval races, drift, ambiguity, UPID tracking and dry-run purity.

## Stage 4: Storage, hosts, Docker, and UI-4 terminals (≈ 6–8 days)

- **Recipes:** disk wipe, ZFS create and add-vdev (including a stripe through `zpool create`), storage add, the node-admin token flow, staged network change with dead-man revert, firewall rules with a lockout check.
- **Linux capability:** the SSH executor, sudoers generated from the installed script recipes, and the starter script recipes.
- **Docker capability:** stack deploy and rollback, plus `hh docker adopt`.
- **UI-4:** terminals (node shell, VM and LXC console, SSH hosts) with recording.
- **Done when:** the ZFS worked example passes on a nested PVE, a stack deploys from the UI, and R-27 and R-28 have tests.

## Stage 5: Steering pack, reference docs, evals, token efficiency (≈ 4–5 days)

- **Steering:** the `steering/` source plus the build (Claude Code plugin, Codex skills, MCP prompts), the `extend-harness` and `capture-recipe` skills, and the `docs://` reference set.
- **Evals:**
  - tier A goldens and the injection suite in CI;
  - tier B and tier C runs;
  - the **token-efficiency suite** against the plain-agent baseline, with results in the README.
- **Done when:** a steering regression fails CI, and the README shows the measured token ratio.

## Stage 6: Cloudflare, Obsidian, usage, UI-5, v1.0 (≈ 5–6 days)

- **Cloudflare:** DNS, tunnels and Access, with `cloudflare.expose_service` and adoption of existing tunnels. Also the public MCP endpoint, for claude.ai and ChatGPT.
- **Obsidian:** tasks, notes and reminders.
- **Usage:** client usage ingest and the usage widget.
- **UI-5:** the Services, Cloudflare, Stacks, Tasks and Audit pages.
- **Release:** the README showcase (a diagram, a demo GIF, the reliability table, token savings), SBOM and provenance, and `v1.0.0`.
- **Done when:** every v1 row in [reliability.md](spec/reliability.md) has a test, and the owner has used the harness instead of the Proxmox UI for two weeks.

## After v1

- More capabilities: `pbs`, `knowledge` (RAG over the vault, runbooks and the lab state), `opentofu`, `home_assistant` and `truenas`.
- MCP Apps, so widgets also render inside Claude and ChatGPT.
- Ceph management recipes.
- Multiple clusters through PDM.

## Open decisions

| # | Decision | Proposal | Needed by |
|---|---|---|---|
| D-1 | ~~Project and repo name~~ | **Decided 2026-11-01:** homelab-harness (`homelab_harness` packages, `hh` CLI). The repo was renamed on 2026-11-01. | — |
| D-2 | ~~Owner auth~~ | **Decided 2026-11-01:** an embedded authorization server ([ADR-0007](adr/0007-owner-auth.md), accepted) | — |
| D-3 | Proxmox node-admin token: minted per plan, or a short-lived token stored for a maintenance window ([proxmox.md §2.3](spec/capabilities/proxmox.md)) | Minted per plan by default, with a window mode available | Stage 4 |
| D-4 | SSH: plain OpenSSH on the tailnet, or Tailscale SSH ([linux-docker.md](spec/capabilities/linux-docker.md)) | OpenSSH, with Tailscale ACLs as the network boundary | Stage 4 |
| D-5 | Compose stacks: managed from a Git repo, or adopted from hosts | A Git repo, with `hh docker adopt` | Stage 4 |
| D-6 | Cloudflare Access IdP for the owner | Email one-time PIN in v1 | Stage 6 |
| D-7 | Is the ChatGPT Secure MCP Tunnel an alternative to a public hostname? | Evaluate it during Stage 6 | Stage 6 |
| D-8 | Obsidian task file layout and the reminder-time convention ([obsidian.md](spec/capabilities/obsidian.md)) | `Tasks/Inbox.md`, with `@HH:MM` | Stage 6 |
| D-9 | GitHub webhook vs polling for vault changes | Polling every 5 minutes in v1 | Stage 6 |
| D-10 | PBS read-only in v1.x, or wait for restore planning in v2 | Read-only in v1.x | After v1 |
| D-11 | Live-eval budget: owner CLI only, or a small API key budget for nightly runs | The owner CLI for manual runs; decide on nightly runs in Stage 5 | Stage 5 |
| D-12 | Assistant panel engine: a bridge to the owner's CLI, API-key mode, or deep links ([ui.md](spec/ui.md#assistant-panel)) | Start with deep links, then add the CLI bridge | Stage 3 |
| D-13 | Node log collector: Grafana Alloy or the OTel Collector | Alloy (first-class journald and Docker sources) | Stage 2 |
| D-14 | Git mirror of lab documents: on by default? | Off by default, and offered during `hh init` | Stage 2 |
