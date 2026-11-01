# ADR-0003: MCP-first; AI clients bring their own subscription; the harness runs no model

- **Status:** accepted (2026-10-31)

## Context

The owner wants to use their Claude and ChatGPT subscriptions with the harness, runs no local models, and doesn't want API keys to be required. Anthropic forbids third parties from routing requests through Claude subscription credentials. OpenAI supports ChatGPT sign-in only for its own clients and recommends API keys for automation. All major clients (claude.ai, Claude Desktop, Claude Code, ChatGPT developer mode, Codex) can connect to remote MCP servers using OAuth. The details are in [clients.md](../spec/clients.md).

## Decision

- The harness's primary interface is a **remote MCP server** (streamable HTTP, OAuth 2.1). The owner's clients connect to it and supply the model.
- The harness calls no LLM in its core paths. Every decision (policy, tiering, previews, retries) is deterministic code.
- Unattended AI work goes through the owner's own, unmodified `claude -p` or `codex exec`, run by a runner on the owner's machine. An optional API-key mode exists for documented automation.
- The harness never stores, reads or relays subscription credentials.

## Alternatives rejected

- **An embedded agent framework (Pydantic AI, LangGraph) as the core.** It needs API keys or a ToS-risky subscription relay, and it duplicates the loop the clients already run well.
- **A model gateway (LiteLLM).** Not needed without model calls. It is also a supply-chain risk (the 2026-03 malicious releases).

## Consequences

- The safety model can't rely on client-side confirmation prompts. The harness enforces approvals itself, out of band ([ADR-0005](0005-plan-approve-apply.md)).
- Model quality differs by client. Steering is shipped in formats every client can consume ([steering.md](../spec/steering.md)).
- Live evals need either the owner's CLI login (manual or nightly runs on the owner's machine) or a small API budget ([testing-and-evals.md](../spec/testing-and-evals.md)).
- Vendor connectors for web clients need a public endpoint. That is the single public surface ([threat-model.md](../spec/threat-model.md)).
