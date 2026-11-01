# Connecting AI clients (bring your own subscription)

> **Status: specification.** It was researched on 2026-10-31 against vendor docs. Vendor policies change, so re-check the sources before each release. Anything marked "(unverified)" came from secondary sources.

## The rule

**The harness never holds, stores, relays or calls a model with the owner's Claude or ChatGPT subscription credentials.** Instead, the owner's own AI clients connect *to* the harness as MCP clients, signed in to their subscriptions in the vendors' own apps. The harness supplies tools, resources and prompts; the client supplies the model.

This is the only pattern that is clearly permitted:
- Anthropic's compliance page prohibits third parties from offering Claude.ai login or routing requests through Free/Pro/Max/Ultra credentials. The Agent SDK in third-party products uses API keys ([source](https://code.claude.com/docs/en/legal-and-compliance)).
- OpenAI's Codex sign-in with ChatGPT is officially supported for the owner's own use. OpenAI still recommends API keys for automation, and pooling or proxying subscriptions is not supported ([source](https://learn.chatgpt.com/docs/auth)).

## Supported clients

| Client | Subscription | How it connects | Network path | Notes |
|---|---|---|---|---|
| **Claude Code** (workstation) | Owner's own Claude login | `claude mcp add --transport http harness https://harness.<tailnet>/mcp`, then OAuth through `/mcp` | Tailnet | Best experience: skills and plugins from the steering pack, plus the statusline usage feed |
| **Codex CLI** (workstation) | Owner's own ChatGPT sign-in | `[mcp_servers.harness] url = "…/mcp"` in `config.toml`, then `codex mcp login harness` | Tailnet | Skills under `.agents/skills`; usage through OTel |
| **claude.ai / Claude Desktop / mobile** | Pro/Max (Free allows one connector) | Settings → Connectors → custom connector → public URL, OAuth | **Public**, because calls come from Anthropic's cloud: Cloudflare Tunnel + Access | Turn off write tools for Research mode. MCP Apps can render widgets later. |
| **ChatGPT (web)** | Plan-dependent (unverified for Plus/Pro) | Custom MCP server in developer mode, OAuth | Public via tunnel, or OpenAI's "Secure MCP Tunnel" (unverified) | Web only. Write tools require confirmation unless the tool is `readOnlyHint`. Skills on ChatGPT are not available on Plus/Pro, so MCP prompts and resources are the steering path. |

## MCP server requirements (what the harness implements)

- **Transport:** streamable HTTP at `/mcp`, implementing spec 2026-07-28 (stateless, `MCP-Protocol-Version` header).
- **Auth:** the harness is an OAuth 2.1 resource server with protected-resource metadata (RFC 9728). It validates resource indicators (RFC 8707) and supports Client ID Metadata Documents, with DCR as a fallback for older clients.
- **Authorization server:** an embedded single-owner server built into the harness. The owner logs in with a passkey (WebAuthn) and a recovery code, and there is no registration. Alternatively, delegate to an existing lab IdP such as Authentik or Keycloak. ADR-0007 decides which.
- **Every authenticated principal is the owner.** Each client gets its own client ID, so audit and usage can tell Claude Code, claude.ai and ChatGPT apart. Tokens can be revoked per client (`hh clients revoke`).
- **Tool annotations:**
  - Read tools: `readOnlyHint: true`.
  - `plan_*` tools: `readOnlyHint: true`, because they don't mutate targets and only write a plan row in the harness.
  - There are **no apply or approve tools**.

  As a result, clients' own confirmation prompts don't fire for normal use. The harness's approvals are the control, and they happen on the owner's phone.
- **Exposure:** Cloudflare routes only `/mcp`, `/.well-known/oauth-*` and the authorization server's endpoints. Everything else returns 404 at the edge.

## Unattended automation (the harness asks an AI to do something)

Some features want a model without a human at the keyboard: nightly health summaries, event triage ("backup failed, what happened?"), and later the web UI chat. Options, in order of preference:

1. **Owner's own CLI, invoked on the owner's machine.** A small `hh agent` runner on the workstation (or a lab VM where the owner signed in interactively) calls `claude -p` or `codex exec` with the harness MCP config and a steering prompt. This is the first-party CLI, unmodified, running on the owner's own login for the owner's own use, which the vendors' docs describe as normal individual usage. The harness only queues the request; the runner pulls it.
2. **API key mode (optional).** If the owner adds an Anthropic or OpenAI API key (Max/Ultra plans include monthly API credits for a linked Console org, per the Oct 2026 support note), the harness can run an embedded agent loop. This is the documented automation path. It is off by default.
3. **Not allowed:** reading `~/.claude/.credentials.json` or `~/.codex/auth.json`, calling vendor endpoints with subscription tokens, spoofing client headers, or serving one subscription to more than one person.

`claude setup-token` tokens are allowed for scripts on the owner's machine. They can't load claude.ai connectors, but local MCP config works.

## Usage visibility

The harness shows what each client used and when (see [observability.md](observability.md#client-usage)):

| Source | What it gives | Client |
|---|---|---|
| Claude Code statusline script | `rate_limits.five_hour` and `seven_day` `used_percentage` and `resets_at`, session cost estimate, context use | Claude Code |
| Claude Code OpenTelemetry (`CLAUDE_CODE_ENABLE_TELEMETRY=1`, OTLP to the harness collector) | `claude_code.token.usage`, `claude_code.cost.usage`, session and active-time metrics, `api_request` events | Claude Code |
| Codex OTel (`[otel]` in config) and app-server rate-limit events (unverified, schema unstable) | API, stream and tool metrics; 5-hour and weekly `usedPercent` | Codex |
| Harness MCP audit | Tool calls, plans and approvals per client ID | All clients |
| None | No consumer-plan usage API exists. Web clients show "tool calls only, quota unknown". | claude.ai, ChatGPT |

The harness never scrapes vendor dashboards or uses session tokens to fetch quotas.
