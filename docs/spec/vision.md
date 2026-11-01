# Vision

> **Status: specification.** This describes what will be built. Nothing here is implemented yet. [roadmap.md](../roadmap.md) says what gets built when.

## One line

**An AI control plane for Proxmox home labs.** You bring the AI you already pay for, Claude or ChatGPT. The harness supplies everything that makes that AI a safe, expert infrastructure operator: typed tools, live inventory, plans with previews, approval on your phone, durable execution, an audit trail, and expert steering.

## The problem

AI assistants can already *talk* about infrastructure. Letting one *operate* infrastructure is a different matter. The existing Proxmox MCP servers show the gap: most expose the raw API, often as `root@pam` with TLS verification off. The best of them let the model approve its own actions by filling in a token argument.

A real operator needs more than that:
- What will this change, exactly? Show the diff before anything happens.
- Can it be undone? If not, ask me in a way the model cannot fake.
- What happened? Every action needs a durable record from request to result, including Proxmox's own task log.
- If the process dies halfway, the job should resume or report honestly, not run twice.
- The AI should know *my* lab and follow good practice: least privilege, backups before risky changes, no public hostname without access control.

## What it is

The harness has four parts:

1. **A control plane** (Python service on Postgres):
   - inventory of nodes, guests, storage, disks, hosts, services and tunnels;
   - the plan, approve, apply engine;
   - durable jobs;
   - the audit log;
   - the credential vault;
   - event ingest and notifications.
2. **An MCP server.** The control plane exposes everything as typed tools, resources and prompts over MCP. Claude (claude.ai, Desktop, Code) and ChatGPT/Codex connect to it with the owner's own subscriptions. The harness holds no model API key and runs no local model.
3. **A steering pack.** Versioned system prompts, skills and runbooks make any connected model behave like a careful senior infra, DevOps and security engineer for *this* lab.
4. **Interfaces for the owner:**
   - in v1, the `hh` CLI and phone approvals through ntfy;
   - after v1, a web UI with multi-terminal panes, a customizable widget dashboard, chat, and live subscription usage.

## What it can do (examples the design must support)

| Request | What happens |
|---|---|
| "What's eating disk on pve2?" | Read tools, so it runs at once. Inventory and live metrics come back with a sourced answer. |
| "Make me an Ubuntu 24.04 VM, 4 cores, 8 GB, on pve1, call it builder" | The model calls `proxmox.guest.plan_create`. The plan shows the template, VMID, storage, cloud-init values, pool and the cost to capacity. Policy auto-approves, because the guest lands in the agent pool and the change is reversible. A durable job tracks the Proxmox task. The result includes a verification read. |
| "I added two drives, make them a ZFS stripe" | Preflight identifies the disks by serial and confirms they are empty: no partitions, signatures, mounts or pool membership. The plan states that **a stripe has no redundancy**, and that Proxmox's API has no stripe level, so the harness runs an exact `zpool create` over SSH. It shows the resulting capacity and the command. This is tier 3: approval comes from the owner's phone and the owner must type the pool name. State is checked again at apply time. |
| "Expose Grafana at grafana.example.com" | The plan combines a Cloudflare tunnel ingress rule, a DNS record and **an Access policy**. A public hostname without an Access policy is refused. |
| "Deploy this compose stack on docker-01" | The Git-tracked compose file is validated with `config`. Image digests are diffed. `up -d` runs over SSH, and the previous digests are recorded for rollback. |
| "Add 'renew certs' to my tasks for Friday" | An Obsidian Tasks line is written to the vault repo through GitHub, and a reminder is scheduled through ntfy. |

## Principles

1. **The model proposes; deterministic code decides.** Models produce structured plan requests. Policy, previews, preflight checks, approvals, retries and execution are plain, tested code.
2. **Nothing writes without a plan.** Every mutation goes through plan, then approve, then apply. No tool performs a write as a side effect of being called.
3. **The model cannot approve its own actions.** Approval arrives out of band, through ntfy, the CLI or the UI, bound to a hash of the exact plan. Approval is never a tool argument.
4. **Least privilege is enforced by Proxmox, not just by policy.** Each capability uses its own privilege-separated API token. Agent-created guests live in a dedicated pool, so the blast radius has an ACL boundary.
5. **Honest outcomes.** An ambiguous write is recorded as `uncertain`, never `failed`, and never retried blindly.
6. **Observable by default.** Every tool call, plan, approval and job is traced and logged with identifiers, never with secrets.
7. **Extensible by asking an agent.** A new capability, such as PBS, TrueNAS or a RAG server, is a package that follows a template and passes a shared contract test kit. The core does not change.
8. **Bring your own AI, legitimately.** The harness supports subscriptions only through the paths the vendors officially support. See [clients.md](clients.md).

## Non-goals (v1)

- A web UI. The CLI and phone come first; the UI vision is recorded in [ui-vision.md](ui-vision.md).
- Running or hosting models. No local models, and no model API keys required.
- Multi-tenant or team use. There is one owner, and every request is authenticated as that owner.
- Replacing Terraform or Ansible for fleet-scale declarative management. An optional OpenTofu backend is a later capability.
- Kubernetes management. Proxmox, Docker and plain Linux are the v1 targets.

## What success looks like

- **Daily use:** the owner manages the lab through it: checks, provisioning, disk work, deployments, tasks.
- **Safety, demonstrated:** a public demo shows a prompt-injection string planted in a VM description that tries to destroy a guest. The harness blocks the destroy and leaves it pending.
- **Reliability, demonstrated:** every failure mode in [reliability.md](reliability.md) has a named test. There is a crash-mid-job test, and a test for an approval used twice.
- **Quality, measured:** steering and tool-use evals run in CI, and a live suite runs against a nested Proxmox.
- **Readable in five minutes:** the README has an architecture diagram, a demo GIF (ask, preview, approve on phone, job, trace) and the reliability table.
