# Connecting AI clients (bring your own subscription)

> **Status: specification, partly implemented.** The `/mcp` server, its tool annotations, the embedded OAuth 2.1 authorization server with passkey owner login (ADR-0007; see [Connecting with OAuth](#connecting-with-oauth-tailnet)), and legacy bearer tokens (see [Legacy bearer tokens](#legacy-bearer-tokens)) are built. The public tunnel for claude.ai and ChatGPT is Stage 6. Client behavior was researched on 2026-10-31 against vendor docs. Vendor policies change, so re-check the sources before each release. Anything marked "(unverified)" came from secondary sources.

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

- **Transport:** streamable HTTP at `/mcp`, implementing spec 2026-07-28 (stateless, `MCP-Protocol-Version` header). *Implemented* with the official MCP Python SDK (`mcp` 2.3), low-level `Server`, stateless with JSON responses. Handshake-era clients (2025-11-25 and earlier) are served too, through the SDK's stateless mode. The tool list is built from the capabilities core discovers through the `homelab_harness.capabilities` entry point.
- **Auth:** the harness is an OAuth 2.1 resource server with protected-resource metadata (RFC 9728). It validates resource indicators (RFC 8707) and supports Client ID Metadata Documents, with DCR as a fallback for older clients. *Implemented:* metadata at `/.well-known/oauth-protected-resource/mcp` (and at the root path); a 401 from `/mcp` carries `WWW-Authenticate: Bearer resource_metadata="…"`. Only access tokens whose audience is exactly `<HH_PUBLIC_URL>/mcp` are accepted.
- **Authorization server:** an embedded single-owner server built into the harness (ADR-0007, option A). *Implemented:* metadata at `/.well-known/oauth-authorization-server`; `/oauth/authorize` (PKCE `S256` required), `/oauth/consent` (needs an owner passkey session; deny by default), `/oauth/token` (`authorization_code` and `refresh_token` only), `/oauth/revoke`, and `/oauth/register` (DCR, public clients only). The owner signs in at `/owner/login` with a passkey, or with a single-use recovery code. There is no registration: the owner is enrolled from the harness host with `homelab-harness-owner enroll`. Access tokens last 15 minutes; refresh tokens rotate, and reuse of an old one revokes the whole grant. Responses include `iss` (RFC 9207).
- **Every authenticated principal is the owner.** Each client gets its own client ID, so audit and usage can tell Claude Code, claude.ai and ChatGPT apart. Every tool call is audited as `mcp.tool_call` with actor `client:<id>`: `cimd:<host>:<path>` for a metadata-document client, `dcr:<id>` for a registered one, or a legacy token's name. `hh clients list` shows them, and `hh clients revoke <id>` (or `homelab-harness-token revoke --client <id>` on the host) ends every grant of one client at once.
- **Tool annotations:**
  - Read tools: `readOnlyHint: true`. *Implemented:* also `idempotentHint: true`, `destructiveHint: false`, and `openWorldHint: false` for tools that only talk to registered targets (a closed set), which is every Proxmox tool.
  - `plan_*` tools: `readOnlyHint: true`, because they don't mutate targets and only write a plan row in the harness.
  - There are **no apply or approve tools**.

  As a result, clients' own confirmation prompts don't fire for normal use. The harness's approvals are the control, and they happen on the owner's phone.
- **Exposure:** Cloudflare routes only `/mcp`, `/.well-known/oauth-*` and the authorization server's endpoints. Everything else returns 404 at the edge.

## Connecting with OAuth (tailnet)

Passkeys and OAuth need HTTPS (loopback aside), so serve the harness over the tailnet with a certificate, for example `tailscale serve --bg --https=443 http://127.0.0.1:8080`, and set `HH_PUBLIC_URL=https://<host>.<tailnet>.ts.net`. It is the issuer, the passkey relying party and the origin of the MCP resource, so clients must use exactly that address ([development.md](../development.md#owner-login-and-oauth)).

1. **Enroll the owner once**, on the harness host: `homelab-harness-owner enroll`. It prints a one-time link (15 minutes) and ten recovery codes; open the link on a device with your passkey and register it. A second `enroll` is refused; `enroll --add-passkey` adds another passkey, and `homelab-harness-owner recovery-codes` replaces the codes.
2. **Claude Code** (flow per the [Claude Code MCP docs](https://code.claude.com/docs/en/mcp), checked 2026-11-03; not yet verified against a live harness):
   ```bash
   claude mcp add --transport http harness https://<host>.<tailnet>.ts.net/mcp
   ```
   then run `/mcp` inside Claude Code and choose to authenticate (or `claude mcp login harness` from the shell). Claude Code reads the protected resource metadata, discovers the authorization server, identifies itself with its client metadata document (or registers through DCR), and opens a browser on `/oauth/authorize`. Its callback is `http://localhost:<random port>/callback`; the harness accepts any port on a registered loopback redirect (RFC 8252). Sign in with your passkey if asked, check the consent screen (client, where the answer goes, the resource), and allow. Claude Code stores and refreshes the tokens itself.
3. **Codex CLI** (flow per the [Codex MCP docs](https://learn.chatgpt.com/docs/extend/mcp?surface=cli), checked 2026-11-03; not yet verified against a live harness). In `~/.codex/config.toml`:
   ```toml
   [mcp_servers.harness]
   url = "https://<host>.<tailnet>.ts.net/mcp"
   ```
   then `codex mcp login harness`, which runs the same browser flow (`--oauth-client-registration cimd|dcr` forces one registration method; the default is `auto`).
4. **claude.ai, Claude Desktop, mobile and ChatGPT** connect from the vendors' clouds, so they need the public route through Cloudflare (Stage 6). The authorization server is ready for them; the tunnel is not built.

To cut a client off: `hh clients list`, then `hh clients revoke <id>`. Its access and refresh tokens stop working at once; it can only come back through a new consent.

*Verified:* the full flow (discovery, CIMD and DCR, PKCE, consent, token exchange, refresh, revocation) runs in the test suite against the ASGI app, including with the MCP SDK's own OAuth client (`OAuthClientProvider`). *Not verified:* a real browser passkey ceremony, and live Claude Code or Codex clients.

## Legacy bearer tokens

> **Legacy, tailnet only.** These are long-lived owner tokens with no expiry or scopes, accepted at `/mcp` only while `HH_MCP_LEGACY_TOKENS=true` (the default for now; it will default to `false` once the OAuth flows below are verified with live clients, and the tokens will then be removed). Prefer OAuth. Never route `/mcp` through the public tunnel while they are on. Revoke a token as soon as a machine is lost.

1. Register targets in `HH_TARGETS_FILE` and create one token per client on the harness host ([development.md](../development.md#mcp-server)):
   ```bash
   homelab-harness-token create --client claude-code   # prints the token once
   homelab-harness-token create --client codex
   ```
   These are `mcp`-role tokens: they work only at `/mcp`. The `hh` CLI uses a separate `owner`-role token (`--role owner`), which is refused at `/mcp`, so never give one to an AI client.
2. **Claude Code** (syntax checked against the Claude Code MCP docs on 2026-11-01):
   ```bash
   claude mcp add --transport http harness http://<tailnet-host>:8080/mcp \
     --header "Authorization: Bearer <token>"
   ```
   Then run `/mcp` inside Claude Code to check the connection. `claude mcp add` does not validate the token.
3. **Codex CLI** (syntax checked against the Codex MCP docs on 2026-11-01). In `~/.codex/config.toml`:
   ```toml
   [mcp_servers.harness]
   url = "http://<tailnet-host>:8080/mcp"
   bearer_token_env_var = "HARNESS_MCP_TOKEN"
   ```
   and export `HARNESS_MCP_TOKEN=<token>` in the shell that runs `codex`. The value is the variable's name, not the token.

Results carry `structuredContent` plus a JSON text rendering. `_meta` has `homelab-harness/as_of` and `homelab-harness/untrusted`. When that flag is true, target-sourced text sits inside `untrusted` objects, and the text rendering says to treat them as data (S7). Neither client connection has been verified against a live client in this PR. The SDK's own client was run against a local server, over both protocol eras.

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
