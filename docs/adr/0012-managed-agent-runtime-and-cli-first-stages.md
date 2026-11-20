# ADR-0012: managed official runtimes, CLI first, documentation-only restart

- **Status:** accepted direction from the maintainer, 2026-11-20. Items marked proposed/open in Stage 1 remain undecided.
- **Decision scope:** product/runtime ownership, repository reset, delivery gates and reuse policy. No new runtime implementation is claimed.

## Context

The old implementation was an MCP-first control plane for AI clients on the owner's workstation, with a broad GUI and infrastructure platform. The maintainer clarified the intended product as a Herder-like workspace specialized for Proxmox: the service runs a real official agent program, provides tools/context/permissions and is driven from our thin CLI. Multi-agent supervision and GUI are later goals.

The maintainer explicitly requested a documentation-only `main`, with all existing code preserved on another branch so it cannot dictate future design. The no-own-loop clarification supersedes the intermediate review proposal which briefly called for a custom loop.

## Decision

1. Prepare a documentation-only active tree: documents, legal notices and minimal Git metadata. Retire source, tests, build/deploy configuration, dependency locks, assets and executable workflows together. No live data is deleted.
2. Preserve the complete previous tree on [archive/pre-cli-restart-2026-11-20](https://github.com/straw-hat-gupta/homelab-harness/tree/archive/pre-cli-restart-2026-11-20), commit `a97f2aacd611f0a6b666f336fda57fad88c27080`. The v0 documents remain unchanged historical reference.
3. Run an unmodified `claude` or `codex` program on a dedicated service guest. That runtime owns its provider login, loop and native history. No custom loop, subscription-token relay or workstation-side brain.
4. Put the client experience, session lifecycle, bounded lab context, deterministic permissions, brokered tools and audit in our product. Keep the Mac replaceable with small saved connection/authentication state.
5. Limit Stage 1 to one owner, one cluster per instance, one agent and one active read-only run. Manual guest setup is accepted. Claude Code is the proposed first backend, not a guarantee of integration support.
6. Use small increments with automated evidence and owner-lab acceptance before advancing. Defer GUI, writes, supervision and broad platform infrastructure.
7. Choose implementation technology and archived components only for a current requirement. The vault is a strong reuse candidate, not an automatic dependency commitment. [Code reuse](../code-reuse.md) defines the review.
8. Preserve safety S1–S10 and secrets requirements. Tighten initial policy: no writes and no automatic approval; native runtime tools cannot bypass the tool service. Runtime credentials remain in supported runtime custody, separate from target secrets.

## Relationship to previous decisions

The old [ADR directory](https://github.com/straw-hat-gupta/homelab-harness/tree/a97f2aacd611f0a6b666f336fda57fad88c27080/docs/adr) is preserved outside the active spec.

| Old ADR | Current treatment |
|---|---|
| 0001: Proxmox rewrite | Historical origin; product specialization retained, original delivery plan replaced. |
| 0002: Python/FastAPI/Postgres workspace | Historical implementation choices; no stack imposed on the new proof. |
| 0003: MCP-first external AI clients | Official-runtime/no-proxy principle retained; workstation entry point replaced by our cluster-hosted runtime and CLI. |
| 0004: DBOS | Durable/ambiguity requirements retained for future writes; engine unselected until needed. |
| 0005: plan/approve/apply | Safety contract retained in the active safety spec; no future write may bypass it. |
| 0006: ntfy | Optional future owner channel; no initial deployment requirement. |
| 0007: embedded OAuth/passkeys | Existing implementation preserved; private CLI pairing must be selected independently. |
| 0008: Grafana stack | Useful reference; basic redacted run/tool visibility first. |
| 0009: brokered vault | Secrecy, grant and encryption protections retained; broad feature delivery and mandatory DB assumptions replaced by scoped adoption. |
| 0010: lab state/recipes/catalog | Freshness and reuse retained; full sync/catalog/Git mirror not initial requirements. |
| 0011: GUI in v1 | Early GUI timing and framework commitment superseded; extensible GUI remains long-term intent. |

## Vendor evidence and limits

Checked 2026-11-20. Claude documents programmatic use of the real CLI, including structured/streamed output and continued sessions; runtime behavior still needs live verification. [Claude CLI documentation](https://code.claude.com/docs/en/headless)

Anthropic's conditions require an unmodified binary and each user's own supported authentication; this is not blanket permission to collect or proxy subscription credentials. [Authentication and hosting conditions](https://code.claude.com/docs/en/legal-and-compliance)

Codex App Server is a supported integration surface for custom clients with authentication, threads and events. Codex also documents local-provider options for LM Studio/Ollama. These are later candidates; no pairing is claimed tested here. [App Server](https://learn.chatgpt.com/docs/app-server), [CLI options](https://learn.chatgpt.com/docs/cli/reference)

## Consequences

No runnable quickstart or historical test count describes the active branch. A future implementation can reuse tested components without reviving the old application. The first proof may reveal runtime isolation/control limits; resolve those explicitly before lab access. A future UI can share the core without fixing its framework now.

Review and merge remain governed by AGENTS.md; this ADR does not authorize an agent to push directly to `main` or merge a PR. It records the desired documentation-only result once the maintainer merges the prepared change.
