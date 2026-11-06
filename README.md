# homelab-harness

[![CI](https://github.com/straw-hat-gupta/homelab-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/straw-hat-gupta/homelab-harness/actions/workflows/ci.yml)

> **Status: Stage 1 in progress.** Merged so far: the service skeleton, Postgres with DBOS and an append-only audit log, the read-only Proxmox adapter with TLS pinning, the vault's crypto core, and OpenTelemetry with a Grafana stack. The MCP server is next. The order is set by the [roadmap](docs/roadmap.md).

**An AI-native control plane and UI for Proxmox home labs.** Your Claude or ChatGPT can already run commands on your nodes. The harness lets it do the same work **with a fraction of the tokens and no guessing**:
- **Lab state, not discovery.** Code keeps a typed, always-current model of the lab and renders compact `lab://` documents. Agents read one page instead of running twenty commands.
- **Logs in one place.** Node journals, Proxmox task logs and container logs are queryable within a budget, with no SSHing around.
- **Recipes, not improvisation.** Tested, typed, composable operations (create a VM, build a ZFS pool, expose a service) that any agent can reuse.
- **Safe by construction.** Every change is a plan with a deterministic preview and **approval on your phone** that the model can't fake. Changes run as **durable jobs**, and secrets are brokered so agents never see them.
- **Observable.** An append-only audit log, OpenTelemetry traces, and failures attributed to the agent, the recipe or the target.
- **A UI that replaces the Proxmox web UI.** It has the same navigation, with plan previews on every action, an AI assistant, and widgets built from a reuse-first catalog.
- **Adopts the lab you already have.** `hh init` works on any existing cluster, read-only.

| Start here | |
|---|---|
| [Vision](docs/spec/vision.md) | What it is, its principles and non-goals |
| [Architecture](docs/spec/architecture.md) | **System diagram of what runs where**, then components, code layout, and the plan, approve, apply flow |
| [Safety model](docs/spec/safety-model.md) | Invariants, risk tiers, previews, approvals |
| [Full specification](docs/spec/README.md) | Every spec doc, in reading order |
| [ADRs](docs/adr/) · [Glossary](GLOSSARY.md) · [Roadmap](docs/roadmap.md) | Decisions, vocabulary, stages |

## Try it on your lab

**[docs/getting-started.md](docs/getting-started.md)** walks through running Stage 1 against a real Proxmox cluster: Docker Compose, the vault, passkey and OAuth, then connecting Claude Code or Codex. It's read-only toward the lab.

## Quick start (development)

```bash
uv sync                      # Python 3.13 workspace, locked dependencies
uv run pytest                # tests
HH_ENV=dev HH_LOG_FORMAT=console uv run homelab-harness   # serves on 127.0.0.1:8080
uv run hh health             # in another terminal
```

There's a container option too: `docker compose -f deploy/compose.yaml up -d --build`. See [docs/development.md](docs/development.md).

## What happened to the old code

The v0 Django/DRF/Celery assistant backend is archived:

- **Code:** the [`v0-django-final`](https://github.com/straw-hat-gupta/homelab-harness/tree/v0-django-final) tag.
- **Docs, audit, and audit cross-check:** [`docs/archive/v0/`](docs/archive/v0/README.md).

## Origins and license

Extracted from the Aiva team project with its contributors' permission. See [ORIGINS.md](ORIGINS.md) and [NOTICE](NOTICE). MIT licensed; see [LICENSE](LICENSE).
