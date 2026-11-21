# Homelab Harness

**A Proxmox-focused workspace around existing agent runtimes.** A thin Mac CLI will connect to a service guest in your cluster. That service will launch the real, unmodified `claude` or `codex` program with homelab tools, relevant context and deterministic access rules.

> **Current state: Stage 1A fixture prototype.** A guest-local launcher, one invented-data MCP tool and automated failure tests are available. Real Claude subscription/guest acceptance is pending. There is no Proxmox access, Mac client, installer, GUI or deployed service yet. The previous implementation remains preserved separately.

Start with the [fixture proof guide](docs/getting-started.md). Development checks are in [development](docs/development.md); the selected scope and limits are in [ADR-0013](docs/adr/0013-claude-fixture-proof.md). Do not provide Proxmox credentials for this proof.

## Start here

| Document | Purpose |
|---|---|
| [Vision](docs/spec/vision.md) | Product, boundaries and long-term intent |
| [Stage 1 contract](docs/stage-1.md) | The next deliverable, small increments and live acceptance gates |
| [Architecture](docs/spec/architecture.md) | What runs where and who owns each harness layer |
| [Roadmap](docs/roadmap.md) | Sequence; no automatic progression or calendar estimates |
| [Specification index](docs/spec/README.md) | Which documents are binding |
| [Project status](docs/project-status.md) | What exists now, separately from historical work |
| [Code reuse](docs/code-reuse.md) | How to inspect and adopt archived components without inheriting the old architecture |
| [Decision 0012](docs/adr/0012-managed-agent-runtime-and-cli-first-stages.md) | Why this direction replaces the old platform plan |

## First experience we are building

1. Manually prepare a dedicated service VM/container in the cluster.
2. Install one official agent runtime and complete its supported subscription login.
3. Connect a narrowly scoped Proxmox read credential through owner-only setup.
4. Open `hh` on the Mac, select a saved harness instance and connect privately.
5. Ask which containers are running, where guests live, or what CPU, memory and storage a node reports.
6. Receive answers backed by typed reads, sources, units and observation times.

These are requirements, not working commands. Management commands and conversational interaction both belong in the CLI. The runtime owns the model/tool loop; our service owns the lab tools, permissions, context and session lifecycle around it. No custom inference loop is planned.

Stage 1 has one owner, one cluster per service instance, one agent and one active run. It excludes target writes, GUI, generated-tool execution, multi-agent supervision, collectors and public remote access. Each small increment must be tried on the owner's lab before the next begins.

Later, the same core can support a cluster-hosted GUI, reusable widgets, controlled operations, roles/jobs, additional runtimes and local or VPS-hosted inference. These are [future intentions](docs/future.md), not requirements to implement now.

## Preserved implementation

The full pre-restart code, tests, vault, UI, configuration and old specifications are preserved on [archive/pre-cli-restart-2026-11-20](https://github.com/straw-hat-gupta/homelab-harness/tree/archive/pre-cli-restart-2026-11-20), commit `a97f2aacd611f0a6b666f336fda57fad88c27080`. Nothing is automatically adopted from it, including the vault. Its useful components remain candidates for deliberate reuse.

The earlier Django product is preserved at `v0-django-final`; its [archived documents](docs/archive/v0/README.md) are history, not current requirements. See [Origins](ORIGINS.md), [NOTICE](NOTICE) and [LICENSE](LICENSE).
