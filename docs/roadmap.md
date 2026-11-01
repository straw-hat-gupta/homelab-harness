# Roadmap

What gets built, in what order, and how we know each stage is done. Every stage ends in something the owner uses. Each stage is a handful of PRs, and each PR has one concern. Effort is in focused days and is rough.

The spec is in [`docs/spec/`](spec/README.md), the decisions are in [`docs/adr/`](adr/), and the vocabulary is in [GLOSSARY.md](../GLOSSARY.md).

## Stage 0: Specification (current)

- [x] Archive v0 at the `v0-django-final` tag, with its docs in `docs/archive/v0/`.
- [x] Write the vision, architecture, safety model, threat model, clients, observability, reliability, extending, steering, testing and evals, UI vision, and capability specs (Proxmox, Linux and Docker, Cloudflare, Obsidian).
- [x] Write ADRs 0001–0008 and the glossary.
- [x] The maintainer reviews the docs and resolves the [open decisions](#open-decisions) marked "before Stage 1" (D-1 and D-2, 2026-11-01).
- [x] Specify secrets: storage, brokered use without exposing values, and owner intake ([secrets.md](spec/secrets.md), ADR-0009).

**Done when:** this PR is merged with its decisions resolved, and AGENTS.md has been rewritten for the new layout.

## Stage 1: Skeleton, plus read-only Proxmox (≈ 4–6 days)

Daily value: "What's going on in my cluster?" from Claude Code, Codex or claude.ai.

**Repo and CI**
- uv workspace (`packages/core`, `packages/sdk`, `capabilities/proxmox`, `cli`), ruff, pyright strict, pytest with testcontainers.
- CI: lint, types, tests, the contract kit, gitleaks, pip-audit, Docker build, docs links. Renovate.

**Core**
- FastAPI app, settings, structlog with redaction, OTel.
- `/healthz` and `/readyz`.
- Postgres with Alembic, DBOS initialized.
- The secrets vault: envelope encryption, KEK providers, `hh secret add/list/rotate/revoke`, the `broker` mode and the redaction scanner. Later stages add grants, intake, `ssh-sign` and egress ([secrets.md](spec/secrets.md#roadmap-placement)).
- Inventory sync workflows, and an audit writer for tool calls.

**MCP**
- Streamable HTTP server at `/mcp`, with the tool registry built from capability manifests.
- Owner OAuth (ADR-0007), with Claude Code and Codex connected over the tailnet.

**Proxmox, read-only**
- `hh proxmox bootstrap` prints the exact `pveum` commands.
- The typed adapter pins TLS.
- All T0 read tools and inventory resources.

**Steering v0**
- The operator prompt as an MCP prompt, plus the `proxmox-health-check` skill.

**Deploy**
- Compose with harness, Postgres, the OTel Collector, Grafana, Prometheus, Tempo, Loki and ntfy, plus the overview dashboard.

**Done when:**
- A clean install followed by `hh doctor` is green (R-23).
- "What's using disk on pveX?" is answered with `as_of` citations in Claude Code and Codex.
- The trace is visible in Grafana.
- The contract kit is green.
- R-16, R-17, R-18, R-24 and R-25 have tests.

## Stage 2: Plan, approve, apply, plus guest operations (≈ 5–7 days)

Daily value: provision and operate guests safely from chat, with approvals on the phone.

- Plan model, hashing, preview renderer, and policy engine (tiers, floors, `policy.toml`).
- Approvals state machine, ntfy actions (ADR-0006), and the `hh approve`, `hh plans` and `hh jobs` commands.
- DBOS jobs: re-preflight, steps with retry classes, UPID polling, verification, outcomes including `uncertain`, and per-scope queues.
- Proxmox T1/T2 operations:
  - power and snapshots;
  - create from template with cloud-init, and clone;
  - config changes, resize and migrate;
  - backup now;
  - destroy (T3).
- Proxmox event webhook ingest, routed to ntfy alerts.

**Done when:**
- "Make me a VM" works end to end, auto-approved in the agent pool.
- Destroy requires typed confirmation.
- Tests for these requirements pass: crash recovery (R-11), approval races (R-05), drift (R-10), ambiguity (R-02), UPID tracking (R-29), concurrency (R-31) and dry-run purity (R-04).

## Stage 3: Storage and hosts (≈ 5–7 days)

Daily value: the "two new drives into a ZFS pool" flow, plus deploying Docker stacks.

**Proxmox storage**
- Disk inventory with SMART.
- Disk wipe.
- ZFS create for every layout, including a stripe through the `linux` capability, plus storage registration.
- Node-admin token minting flow.

**Linux capability**
- SSH adapter, typed argv operations and the sudoers generator.
- The out-of-band revert path, which unblocks `network.apply`.

**Docker capability**
- Stacks from Git, with config validation, digest diff, `up -d` and rollback.

**Proxmox network and firewall**
- Staged network apply with a dead-man revert, behind a flag until it is tested.
- Firewall rule changes with a lockout check.

**Done when:** the ZFS worked example in [proxmox.md](spec/capabilities/proxmox.md) passes on a nested PVE, and R-27 and R-28 have tests.

## Stage 4: Steering pack v1, plus evals (≈ 3–4 days)

- The full `steering/` source, the build script that generates the Claude Code plugin, Codex skills, claude.ai zips, MCP prompts and resources, and a CI sync check.
- Tier A golden-transcript evals and the injection suite in CI (R-32).
- The tier B live runner (owner CLI or an API budget).
- The tier C nested-PVE suite, with results recorded in `docs/verification.md`.

**Done when:** a regression in steering or tool descriptions fails CI, and the README publishes the eval scores.

## Stage 5: Cloudflare, plus Obsidian tasks (≈ 4–5 days)

- The Cloudflare capability: DNS, tunnels with ingress, Access. The rule "no public hostname without Access" is enforced (R-30).
- The harness's own public MCP endpoint goes behind a tunnel and Access, so claude.ai and ChatGPT can connect.
- The Obsidian capability: a Tasks parser, task add, complete and reschedule (T1), note edits through a PR (T2), and reminders through DBOS to ntfy (R-21).

**Done when:**
- "Expose Grafana at grafana.example.com" produces one combined plan, and applying it works.
- Tasks added from claude.ai on a phone show up in Obsidian.
- A dated task triggers a reminder.

## Stage 6: Usage, automations, v1.0 (≈ 3–4 days)

- Client usage ingest: the Claude Code statusline script, OTel from both CLIs, `hh usage`, and a Grafana usage dashboard.
- The `hh agent` runner: scheduled health summaries and event triage through the owner's `claude -p` or `codex exec`.
- Showcase work:
  - the README rewrite, with a diagram, a demo GIF and the reliability table with every Test cell filled;
  - an SBOM and provenance for the image;
  - a `v1.0.0` tag.

**Done when:** every v1 row in [reliability.md](spec/reliability.md) has a test, and the owner has used the harness daily for two weeks.

## After v1

- **Web UI** ([ui-vision.md](spec/ui-vision.md)): dockview shell, multi-terminal panes, widget dashboard, approvals inbox, live usage widget, chat.
- **Consoles:** a proxied Proxmox termproxy for node, VM and LXC shells, with recording.
- **Further capabilities:** `knowledge` (RAG over the vault, runbooks and lab docs, using full-text search plus agentic retrieval), `pbs`, `opentofu`, `home_assistant`, `truenas`.
- MCP Apps, so widgets render inside Claude and ChatGPT.

## Open decisions

| # | Decision | Proposal | Needed by |
|---|---|---|---|
| D-1 | ~~Project and repo name~~ | **Decided 2026-11-01:** homelab-harness (`homelab_harness` packages, `hh` CLI). The repo was renamed on 2026-11-01. | — |
| D-2 | ~~Owner auth~~ | **Decided 2026-11-01:** an embedded authorization server ([ADR-0007](adr/0007-owner-auth.md), accepted) | — |
| D-3 | Proxmox node-admin token: minted per plan, or a short-lived token stored for a maintenance window ([proxmox.md §2.3](spec/capabilities/proxmox.md)) | Minted per plan by default; a window mode is available | Stage 3 |
| D-4 | SSH: plain OpenSSH on the tailnet, or Tailscale SSH ([linux-docker.md](spec/capabilities/linux-docker.md)) | OpenSSH, with Tailscale ACLs as the network boundary | Stage 3 |
| D-5 | Compose stacks: managed from a Git repo, or adopted from hosts | A Git repo, with a one-time adoption command | Stage 3 |
| D-6 | Cloudflare Access IdP for the owner | Email one-time PIN in v1 | Stage 5 |
| D-7 | Is the ChatGPT Secure MCP Tunnel an alternative to a public hostname? | Evaluate it during Stage 5 | Stage 5 |
| D-8 | Obsidian task file layout and the reminder-time convention ([obsidian.md](spec/capabilities/obsidian.md)) | `Tasks/Inbox.md`, with `@HH:MM` | Stage 5 |
| D-9 | GitHub webhook vs polling for vault changes | Polling every 5 minutes in v1 | Stage 5 |
| D-10 | PBS read-only in v1.x, or wait for restore planning in v2 | Read-only in v1.x | After v1 |
| D-11 | Live-eval budget: owner CLI only, or a small API key budget for nightly runs | Owner CLI for manual runs; decide on nightly runs in Stage 4 | Stage 4 |
