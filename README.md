# agentic-assistant

[![CI](https://github.com/straw-hat-gupta/agentic-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/straw-hat-gupta/agentic-assistant/actions/workflows/ci.yml)

> **Status: specification stage.** There is no runnable code yet. The design is complete, and code lands in stages. See the [roadmap](docs/roadmap.md).

**An AI control plane for Proxmox home labs.** You bring the Claude or ChatGPT you already pay for, connected over MCP. The harness makes that model a safe, expert operator for your lab:
- typed tools and live inventory for Proxmox, Linux, Docker, Cloudflare and Obsidian tasks;
- every change goes through a **plan with a deterministic preview**, with **approval on your phone** that the model can't fake;
- **durable jobs** that survive restarts without repeating a write;
- an append-only audit trail and OpenTelemetry traces end to end;
- a versioned **steering pack** that makes models careful infra, DevOps and security engineers.

| Start here | |
|---|---|
| [Vision](docs/spec/vision.md) | What it is, its principles and non-goals |
| [Architecture](docs/spec/architecture.md) | Components, code layout, and the plan, approve, apply flow |
| [Safety model](docs/spec/safety-model.md) | Invariants, risk tiers, previews, approvals |
| [Full specification](docs/spec/README.md) | Every spec doc, in reading order |
| [ADRs](docs/adr/) · [Glossary](GLOSSARY.md) · [Roadmap](docs/roadmap.md) | Decisions, vocabulary, stages |

## What happened to the old code

The v0 Django/DRF/Celery assistant backend is archived:

- **Code:** the [`v0-django-final`](https://github.com/straw-hat-gupta/agentic-assistant/tree/v0-django-final) tag.
- **Docs, audit, and audit cross-check:** [`docs/archive/v0/`](docs/archive/v0/README.md).

## Origins and license

Extracted from the Aiva team project with its contributors' permission. See [ORIGINS.md](ORIGINS.md) and [NOTICE](NOTICE). MIT licensed; see [LICENSE](LICENSE).
