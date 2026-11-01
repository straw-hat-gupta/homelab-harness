# Capability: `cloudflare`

> **Status: specification.** It describes what will be built. Nothing here is implemented yet. Terms follow the [glossary](../../../GLOSSARY.md). The tiers and the plan → approve → apply flow are defined in [safety-model.md](../safety-model.md).

This capability manages how lab services are exposed to the internet: DNS records, Cloudflare Tunnels and their ingress rules, and Cloudflare Access applications and policies. It exists to make one sentence safe: "Expose Grafana at grafana.example.com."

## Scope (v1)

| In scope | Out of scope (v1) |
|---|---|
| DNS records in the owner's zones | Registrar, WAF rules, caching, Workers, R2 |
| Remotely managed tunnels: create, configure ingress, rotate the connector token | Locally managed `config.yml` tunnels. Adoption may come later. |
| Access applications and policies: self-hosted apps, email or IdP rules, service tokens for machine clients | Zero Trust device posture, Gateway, WARP |
| The harness's own public MCP endpoint (see the last section) | |

## Why the REST API, not Cloudflare's remote MCP server

Cloudflare's recommended remote MCP server (`https://mcp.cloudflare.com/mcp`) works in "code mode": the model writes code that runs against the *entire* Cloudflare API. That is the wrong shape for a safety layer:
- No plan exists that the owner can preview.
- Arbitrary combinations of calls can't be classified into risk tiers.
- The token behind it has to be broad.

The harness calls the REST API directly. It uses a fixed, small operation set and narrow tokens. The owner can still connect Cloudflare's MCP server to their own client for *read-only exploration*, outside the harness.

## Credentials and least privilege

The harness holds **separate API tokens**, never the Global API Key:

| Token | Permissions | Scope | Used by |
|---|---|---|---|
| `cf-read` | Zone:Read, DNS:Read; Account: Cloudflare Tunnel:Read, Access: Apps and Policies:Read | The registered zones and account | Read tools and preflight |
| `cf-dns` | Zone · DNS · Edit | **One zone per token**, one token per managed zone | DNS plans |
| `cf-tunnel` | Account · Cloudflare Tunnel · Edit | The account | Tunnel and ingress plans |
| `cf-access` | Account · Access: Apps and Policies · Edit | The account | Access plans |

Every token gets:
- a **client IP filter**, set to the lab's egress IP or IPs;
- a **TTL**, 90 days by default, with expiry raised as an event 14 days ahead.

`aa target add cloudflare` prints the exact token templates. `cloudflare.target.check` verifies that each token exists, is active, and has no permissions beyond its template. It uses the token-verify endpoint and compares the declared scopes. The permission-group names are (unverified) and must be checked against the current dashboard before implementation.

## Adapter behavior

- **HTTP:** `httpx` with a 10 s timeout. Cloudflare's v4 envelope (`success`, `errors[]`) maps to shared exceptions: `AuthRejected` for 401/403, `NotFound`, `Conflict` (code 81057, record already exists), `RateLimited` for 429 (honor `Retry-After`), and `ProviderError` for 5xx. Error messages are reduced to Cloudflare's numeric codes and a safe message; raw bodies are never surfaced.
- **Idempotency:**
  - **DNS create:** before creating, look the record up by `(type, name, content)`. A matching record means the step already succeeded.
  - **Tunnel ingress:** a full-document PUT of the configuration, so it is idempotent. The plan records the configuration `version` it was based on, and apply refuses to run if the live version has changed (drift).
  - **Access app create:** looked up by domain first. Policies are created inside the app.
- **Retries:** reads and idempotent writes retry on 429 and 5xx with backoff. No write retries after a read timeout without the lookup check above.

## Read tools (T0)

| Tool | Returns |
|---|---|
| `cloudflare.zone.list` | Zones visible to `cf-read` |
| `cloudflare.dns.list` | Records for a zone or name, including proxied status and TTL |
| `cloudflare.tunnel.list` | Tunnels, status, connector health, and the hosts running `cloudflared` |
| `cloudflare.tunnel.ingress` | The current ingress rules (hostname → service) with the config version |
| `cloudflare.access.list` | Access apps with their domains, policies and session duration |
| `cloudflare.exposure.report` | **A derived view:** every public hostname, its origin service, whether it is proxied, and **whether an Access policy covers it**. Uncovered hostnames are flagged. |
| `cloudflare.target.check` | Token scope and expiry drift |

## Plan tools

| Tool | Default tier | Preflight | Preview | Executor | Verification | Rollback |
|---|---|---|---|---|---|---|
| `cloudflare.expose.plan_service` | **T3** (safety floor: public exposure) | The hostname is free, or the existing record points at this tunnel. The origin service resolves from the `cloudflared` host. A tunnel exists. **An Access policy is defined in the request.** | A composite: DNS record (CNAME → `<tunnel>.cfargotunnel.com`, proxied), ingress rule diff, Access app and policy (who may log in), and a reachability note | Ordered steps: Access app and policy, **then** ingress, **then** DNS. Access goes first so the hostname is never reachable unprotected. | The hostname resolves. An unauthenticated request gets the Access login (302 to `cloudflareaccess.com`). | Reverse order: DNS, then ingress, then Access, as a generated `plan_unexpose` |
| `cloudflare.expose.plan_unexpose` | T2 | The hostname is exposed through a tunnel this harness manages | What is removed | DNS delete, ingress rule removal, Access app delete (optional) | The name no longer resolves to the tunnel | Re-expose plan |
| `cloudflare.dns.plan_record` (create, update, delete) | T2; **T3** for apex or MX records, or for records that `cloudflare.exposure.report` says carry traffic | The record exists or doesn't; TTL and proxied are valid | A before and after record diff | Create, update or delete | A read-back matches | The inverse operation (shown) |
| `cloudflare.tunnel.plan_ingress` | T2 for removing a rule; **T3** for adding or changing a hostname rule (public exposure floor) | Config version recorded; every hostname rule has Access coverage | The ingress rule diff, which keeps the catch-all `http_status:404` last | Full configuration PUT | A read-back matches the version and is newer | PUT of the previous configuration (recorded) |
| `cloudflare.access.plan_policy` | T2; **T3** when a policy is loosened (adding `everyone`, widening an email domain, `bypass`) | The app exists | A policy diff with a plain-language "who can get in" before and after | Update the policy | Read-back | The previous policy (recorded) |
| `cloudflare.tunnel.plan_rotate_token` | T2 | The connector host is known (`linux` target) | The new token is delivered to the host's `cloudflared` service, then restarted | Rotate through the API, then `linux.service.plan_restart` | The connector reconnects | n/a. The old token is revoked only after reconnect. |

### Policy floors

These are code-level floors. Config can't lower them.

1. **No public hostname without Access.** Any plan whose result would leave a proxied, tunnel-backed hostname uncovered by an Access application is **refused at plan time**. The only exceptions are hostnames on an explicit `public_allowlist` in policy config, and adding to that list is T3.
2. **No `bypass` or `everyone` policy without T3 and typed confirmation of the hostname.**
3. **The ingress catch-all stays last and returns 404.** A plan that would remove or reorder it is refused.

## Resources and prompts

- **Resources:**
  - `cloudflare://exposure`: the exposure report.
  - `cloudflare://zone/<name>/dns`: the zone's records.
- **Prompt:** `expose-service-safely`, a runbook:
  1. Confirm the origin is reachable on the tailnet first.
  2. Choose a hostname.
  3. Choose who may log in.
  4. Plan the exposure.
  5. Verify that unauthenticated requests are challenged.

## The harness's own public endpoint

claude.ai and ChatGPT connectors call the harness's MCP server from the vendors' clouds, so that one endpoint has to be publicly reachable (see [clients.md](../clients.md)). It is exposed **through this capability's own rules**, and [threat-model.md](../threat-model.md) analyzes it:

- `cloudflared` runs next to the harness and publishes only the path prefix `/mcp` (and the OAuth endpoints) on `mcp.<owner-domain>`. The REST API, ntfy action callbacks, and any future UI stay on the tailnet.
- The MCP endpoint is authenticated by **the harness's OAuth 2.1 authorization server**, with the owner as the only resource owner. It is not behind an interactive Access login, because vendor clouds can't complete one. Access may still be used to restrict it to the vendors' published IP ranges, where those exist (unverified for ChatGPT).
- The bootstrap is a special case. `aa setup public-endpoint` produces a T3 plan that runs the exposure with `public_allowlist: [mcp.<domain>]`. It is the only allowlisted hostname by default.
- `cloudflare.exposure.report` always lists this endpoint first, so its exposure is never forgotten.

## Test plan

| Layer | Tests |
|---|---|
| Adapter | Recorded API fixtures for every endpoint used. Error mapping covers 401, 403, 404, the 81057 conflict, 429 with `Retry-After`, and 5xx. Raw error bodies never reach logs or tool output; a planted fake token never appears either. |
| Idempotency | A DNS create after a simulated timeout finds the existing record and succeeds without a duplicate. Ingress apply is refused when the config version drifted. |
| Policy floors | Property test: any sequence of planned DNS, ingress and Access changes that ends with an uncovered public hostname is refused. A `bypass` policy needs T3. Removing the catch-all is refused. |
| Composite ordering | `plan_service` executes Access before ingress before DNS. A crash between steps leaves no hostname reachable without Access. This is checked at every step boundary. |
| Exposure report | A fixture account with covered, uncovered and allowlisted hostnames is classified correctly. |
| Evals | Golden transcript: "make grafana public, skip the login" leads to a refused plan, and the client explains the Access requirement. |

## Open questions

1. IdP for Access policies: one-time PIN by email (no setup), or a GitHub or OIDC IdP? The proposal is email OTP to the owner's address in v1.
2. Should the harness manage `cloudflared` installation on hosts, through `linux` and `docker` plans, or assume it is pre-installed? The proposal is to assume pre-installed and verify it in `target.check`.
3. ChatGPT's "Secure MCP Tunnel" option may avoid a public hostname for ChatGPT entirely (unverified). Evaluate it before committing to a single public endpoint design.
4. Vendor egress IP ranges for an Access IP allowlist: Anthropic publishes some (unverified, check the current list); OpenAI unknown.
