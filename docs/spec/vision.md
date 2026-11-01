# Vision

> **Status: specification.** This describes what will be built. [roadmap.md](../roadmap.md) says what gets built when, and which parts already exist.

## One line

**An AI-native control plane and UI for Proxmox home labs.** It replaces the Proxmox web UI. It keeps a deterministic, always-current picture of the lab and a library of tested operations. Any agent (Claude, ChatGPT, Codex) can do real work in the lab **with a fraction of the tokens, and no guessing**.

## The problem

You can already install Claude Code or Codex on every node and let it configure things. It works, but it is wasteful and fragile:
- **Discovery every time.** Every session re-learns the lab from scratch: `pvesh get` here, `zpool status` there, `ip a`, `journalctl`. That costs tokens and time, and the agent's picture of the lab is different every run.
- **Improvised commands.** The same operation (create a VM from a template, add disks to a pool, expose a service) gets re-invented each time, with different flags and different mistakes.
- **No memory, no audit.** When something breaks, you can't tell whether the agent asked for the wrong thing, the commands were wrong, or the target failed.
- **No guardrails.** A root shell, plus whatever the model decides.
- **Two separate worlds.** The Proxmox web UI for humans, a terminal for agents, and nothing connecting them.

## What it is

1. **Lab state, maintained by code, not by the model.**
   - Sync jobs read Proxmox, Linux hosts, Docker and Cloudflare. They write one typed model of the lab: nodes, guests, storage, ZFS, disks, networks, firewall, backups, services, tunnels and DNS.
   - From that model, deterministic code renders compact **lab documents** (`lab://overview`, `lab://nodes/pve1`, `lab://storage`, …).
   - An agent reads one short page instead of running twenty discovery commands.
   - An optional Git mirror keeps the history of every change to the lab.
   - See [lab-state.md](lab-state.md).
2. **Central lab logs.** Node journals, Proxmox task logs and container logs are collected in one place. Agents query them by budget (node, unit, time window, match) instead of SSHing around. See [lab-state.md](lab-state.md#lab-logs).
3. **A recipe library.** Common operations are tested, versioned, parameterized **recipes**: provision a VM, add disks to ZFS, expose a service, deploy a stack, rotate a certificate.
   - Agents pick a recipe and fill in typed parameters.
   - They don't write commands, and recipes are built to be reused and composed by agents.
   - Every run goes through plan, preview, approval, durable job and verification.
   - See [recipes.md](recipes.md).
4. **A web UI that replaces the Proxmox GUI.**
   - The same navigation: datacenter, then nodes, then guests and storage. Per-object views: summary, console, hardware, snapshots, backups, firewall, tasks, logs.
   - With AI wired in: a context-aware assistant panel, plan previews on every action, terminals and customizable dashboards.
   - Everything is built from a shared catalog of data sources and widget templates.
   - See [ui.md](ui.md) and [catalog.md](catalog.md).
5. **An MCP server.** Lab documents, logs, read tools, recipes and the catalog are exposed as MCP resources, tools and prompts. The owner connects their own Claude or ChatGPT subscriptions ([clients.md](clients.md)). The harness runs no model.
6. **A steering pack and Proxmox knowledge.** Prompts, skills and runbooks make agents act like careful senior infra, DevOps and security engineers. Curated Proxmox, ZFS, Cloudflare and Docker reference docs are available as resources, so agents don't have to search the web ([steering.md](steering.md)).
7. **Easy adoption of an existing lab.** `hh init` connects to a lab that's already running, with any number of nodes, existing names, storage and guests. It discovers everything read-only and leaves the lab's own configuration untouched. See [onboarding.md](onboarding.md).

All of this runs on one core: plans, approvals on your phone, durable jobs, audit, brokered secrets, and OpenTelemetry ([architecture.md](architecture.md), [safety-model.md](safety-model.md)).

## What it can do (examples the design must support)

| Request | What happens |
|---|---|
| "What's eating disk on pve2?" | The agent reads `lab://nodes/pve2` and `lab://storage`: about 1–2k tokens, cited with `as_of`. No shell. |
| "Why did the backup fail last night?" | `logs.query(node="pve1", source="task", type="vzdump", since="24h")` returns the failing task's trimmed log and the related journal lines. The answer cites the lines. |
| "Make me an Ubuntu 24.04 VM, 4 cores, 8 GB, on pve1, call it builder" | The agent runs `recipe:proxmox.guest.create_from_template` with typed parameters. The preview shows the template, VMID, storage, cloud-init and capacity impact. It is T1 in the agent pool, so it auto-approves. A durable job runs it and verifies the result. |
| "I added two drives, make them a ZFS stripe" | The agent runs `recipe:storage.zfs.create_pool` (layout stripe). It identifies disks by serial and refuses non-empty ones. The plan warns "no redundancy", shows the exact `zpool create`, and is T3 with typed confirmation on your phone. |
| "Expose Grafana at grafana.example.com" | `recipe:cloudflare.expose_service` composes Access, then the tunnel ingress, then DNS. A hostname without Access is refused. |
| "Add a widget in my top bar showing pve2's ZFS health" | The agent looks in the catalog, which already has the `zfs.pool_health(node)` data source and the `status-list` template. It writes a **widget config**, not new code, and submits it as a T1 layout plan. |
| "Something's wrong with the media VM" | The UI's assistant panel already has the VM context. It reads the guest document, recent tasks and logs, and offers recipes to fix the problem, each with a preview. |

## Principles

1. **Deterministic state; the model reads, not discovers.** Facts about the lab come from sync code, with `as_of`. Agents never need to run discovery commands for what the lab state already knows.
2. **Recipes before commands.** If an operation is common, it exists as a tested recipe. Agents compose recipes. A raw command is the exception (T3, exact argv shown).
3. **Reuse before create.** For recipes, data sources, widgets and docs, agents and contributors check the catalog first, and extend what's there instead of duplicating it ([catalog.md](catalog.md)).
4. **The model proposes; deterministic code decides.** Policy, previews, preflight, approvals, retries and execution are tested code.
5. **Nothing writes without a plan, and the model can't approve its own** ([safety-model.md](safety-model.md)).
6. **Least privilege, enforced by the target:** Proxmox ACLs, pools, scoped tokens, brokered secrets.
7. **Honest outcomes and attributable failures.** Every failure is classified as agent error, recipe error or target error ([observability.md](observability.md#failure-attribution)).
8. **Token budget is a feature.** Lab documents, tool outputs and logs have size budgets, and the token savings are measured against a plain-agent baseline ([testing-and-evals.md](testing-and-evals.md#token-efficiency)).
9. **Fits the lab you already have.** It adopts existing clusters, names and layouts. It never needs a reinstall, and imposes no naming scheme.
10. **Bring your own AI, legitimately** ([clients.md](clients.md)).

## Non-goals (v1)

- Running or hosting models, or requiring model API keys.
- Multi-tenant or team use. There is one owner.
- Replacing Grafana for deep metrics. The UI embeds or links to Grafana panels.
- Kubernetes management, and fleet-scale declarative management (an OpenTofu backend is a later capability).
- Hosting the UI publicly. It is served on the tailnet only.

## What success looks like

- **The owner stops opening the Proxmox web UI.** The harness UI and agents cover daily operations.
- **Token savings, measured:** the same task suite runs with the harness and with a plain Codex or Claude shell on the node. The README publishes tokens, tool calls, time and success rate for both.
- **Adoption in minutes:** on an existing 3-node cluster, `hh init` reaches a populated lab state and UI without changing the lab's configuration (apart from the harness's own user and tokens, created with the owner's approval).
- **Safety, demonstrated:** an injection planted in a VM description never causes a T2+ action.
- **Reliability, demonstrated:** every row in [reliability.md](reliability.md) has a test.
- **Clean extensibility:** a new widget or recipe is added by an agent that reuses catalog parts. The diff review shows no duplicated data sources, templates or helpers.
