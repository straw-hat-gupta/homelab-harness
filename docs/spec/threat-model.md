# Threat model

> **Status: specification.** This lists the threats the design must handle. Each mitigation links to the rule or test that enforces it. Review this document whenever a capability or exposure path is added.

## Assets

| Asset | Why it matters |
|---|---|
| Proxmox cluster and guests | Every service in the lab, plus data on VM disks |
| Disks and pools | Irreplaceable data |
| Owner's access paths | Tailscale, SSH, the Proxmox UI on 8006, management networks. Losing them means physical recovery. |
| Capability tokens in the vault | Each one is a scoped key to a target |
| Vault encryption keys | Decrypt every token |
| Public exposure surface | Cloudflare tunnels, DNS, Access policies |
| Audit log | Evidence of what happened. It must not be rewritable by the app. |
| Obsidian vault content | Personal notes |
| Owner's AI accounts | Subscriptions. The harness never holds these credentials. |

## Trust boundaries

```
 [Internet] ──(Cloudflare edge + Access, OAuth 2.1)──► cloudflared ──► harness /mcp only
 [Vendor clouds: claude.ai, ChatGPT] ─────────────────┘
 [Tailnet: owner devices, harness, targets] ── everything else (REST for CLI/UI, ntfy, Grafana, SSH, PVE API)
 [harness process] ──(scoped tokens)──► targets
 [target-sourced text] ──► clients' context (untrusted)
```

## Threats and mitigations

| # | Threat | Mitigation | Enforced by |
|---|---|---|---|
| T-01 | **Prompt injection** through target text (a VM description, note, log or DNS TXT record) makes a model request a destructive action | T2/T3 always need owner approval, shown as harness-rendered previews. Provenance marking blocks T1 auto-approval. Target text is delimited in responses. | Safety S2, S4 and S7; the injection eval suite |
| T-02 | The model misdescribes the action it is asking the owner to approve | The approval message shows only the deterministic preview. The model's prose is never part of the approval surface. | Safety "Plans and previews"; a golden test that the ntfy body comes from the preview renderer |
| T-03 | The model approves its own plans, or replays an approval | No approve tool over MCP. Approval tokens are single-use and bound to a hash, and they expire. | S2, S3; approval race tests |
| T-04 | A stale plan is applied after the target changed | Preflight runs again at apply time against the recorded `observed` facts. Proxmox `digest` handles concurrency. | S5; drift tests |
| T-05 | A duplicate external action follows a crash or retry | DBOS step idempotency. Unsafe steps are never replayed, and the job ends `uncertain`. | S6; crash-recovery tests |
| T-06 | The public MCP endpoint is attacked (scanning, credential stuffing, OAuth abuse) | Only `/mcp` and the OAuth endpoints are public; the edge returns 404 for every other path. Vendor connectors can't complete an interactive Access login, so this hostname is the single default entry on `public_allowlist` ([cloudflare.md](capabilities/cloudflare.md)). It is protected by the harness's OAuth 2.1, plus an Access IP-allowlist policy for vendor egress ranges where the vendor publishes them (unverified per vendor). OAuth 2.1 with PKCE and resource indicators, single owner identity, short token lifetimes, rate limits. The REST API, ntfy callbacks and Grafana stay on the tailnet. | [clients.md](clients.md); a deploy test checking that only the allowlisted paths are routable through the tunnel (Stage 6). *Implemented (ADR-0007):* PKCE S256 only, audience-bound tokens, 15-minute access tokens, refresh rotation, a single passkey owner, and per-address plus total rate limits on login, authorize, token and registration: `test_oauth.py::test_authorization_request_refusals`, `::test_pkce_and_code_failures_at_the_token_endpoint`, `::test_dcr_is_rate_limited`, `::test_login_is_rate_limited`. The tunnel and its path allowlist are not built yet. |
| T-07 | Theft of an MCP access token (an attacker gets a client's token) | Tokens are scoped to the MCP resource, short-lived, and revocable from the CLI. A stolen token still cannot approve anything (S2). The worst case is reads and plan creation, and every plan is shown to the owner. | S2. *Implemented:* `test_oauth.py::test_expired_wrong_audience_and_revoked_access_tokens_get_401` (expiry, audience, `hh clients revoke`), `::test_refresh_rotates_and_reuse_revokes_the_family`, `::test_revocation_endpoint_ends_the_grant`, `::test_mcp_exposes_no_approval_tool` |
| T-08 | Harness compromise (RCE in a dependency) | Least-privilege tokens bounded by target ACLs (S8). No root on Proxmox. The vault key lives in the environment or a file outside the DB. The app DB role cannot UPDATE or DELETE audit rows. Pinned and hashed deps, `pip-audit`, Renovate, SBOM. | S8, S9; CI supply-chain jobs |
| T-09 | Lockout: a network, firewall, SSH or ACL change cuts off access | These are T3 floors. A preflight lockout check asserts the harness IP and owner tailnet keep 8006/22. Network apply uses Proxmox's staged config with an auto-revert timer unless the owner confirms afterwards. | Safety floors; [proxmox.md](capabilities/proxmox.md) network section |
| T-10 | Wrong disk wiped (device names shift, `/dev/sdb` ≠ the disk the owner meant) | Disks are identified by `/dev/disk/by-id` plus serial. Preflight checks that the disk is empty (no partitions, signatures, mounts, or ZFS/LVM/Ceph membership). T3 typed confirmation of the serial suffix. | proxmox.md ZFS section; fixtures of non-empty disks |
| T-11 | Accidental public exposure of an internal service | Publishing a hostname without an Access policy is refused (floor). DNS and tunnel changes are T3. | [cloudflare.md](capabilities/cloudflare.md) |
| T-12 | Secrets leak into logs, traces, previews, errors or client context | Redaction processors in structlog and the OTel span processor. Tokens are never returned. The canary-secret contract test covers every capability. Provider error bodies are mapped to safe messages. | S9; the contract kit's redaction test |
| T-13 | Subscription ToS violation (account banned) | The harness never stores, relays or uses Claude/ChatGPT subscription credentials. Clients connect *to* the harness. Unattended automation invokes the owner's own unmodified CLIs on the owner's machine. | [clients.md](clients.md); ADR-0003 |
| T-14 | Approval channel spoofing (a fake ntfy callback) | Callback tokens are HMAC-signed, single-use and bound to the plan hash. The callback endpoint is tailnet-only. The ntfy topic has access control. | approvals tests |
| T-15 | Vault notes exfiltrated through a connected client | Path allowlist and size limits on note reads. The owner decides which clients connect. Note reads are audited. | [obsidian.md](capabilities/obsidian.md) |
| T-16 | Supply chain: a malicious package update (the 2026 LiteLLM-style incident) | Locked, hashed dependencies. No auto-merge of dependency updates. Minimal dependency set. A model gateway is not needed, because the harness calls no model. | CI |
| T-17 | An agent exfiltrates a secret it was allowed to *use* | Brokered modes keep values out of the agent's reach (`broker`, `ssh-sign`, `http-inject`). The `env` mode is labelled exposing and needs T3. Egress routes pin the upstream, so a granted token can't be sent elsewhere. A redaction scanner covers every output. | [secrets.md](secrets.md); R-34, R-36 |
| T-18 | Phishing through secret intake (a model or an attacker sends the owner a fake "enter your token" link) | Intake pages are served only by the harness on the tailnet and require an owner passkey session. ntfy shows the requesting client and purpose. URL elicitation shows the full URL before opening it. | R-37. *Implemented so far:* the owner passkey session (HttpOnly, `SameSite=Lax`, `__Host-` and `Secure` over HTTPS, 15-minute idle timeout) and the CSRF and `Origin` checks that intake pages will reuse: `test_oauth.py::test_secure_cookie_flags_over_https`, `::test_consent_needs_a_session_and_csrf_and_deny_is_explicit`, `::test_idle_sessions_expire` |
| T-19 | KEK theft, or a backup leak | The KEK lives outside Postgres (systemd-creds/TPM or a root-only age file). DB dumps contain only ciphertext. KEK rotation rewraps DEKs. | R-25 |
| T-20 | Server-side request forgery through a client ID metadata document (an attacker's `client_id` URL makes the harness fetch an internal address) | `https` only; every resolved address must be public (no loopback, RFC 1918, link-local, tailnet CGNAT or ULA ranges), and the connection is pinned to the checked address; no redirects, 5 s, 5 KiB, JSON only; the fetched document must name itself | `test_auth_cimd_fetch.py`, `test_auth_rules.py::test_public_address_rules` |
| T-21 | Consent phishing (a malicious client asks the owner to approve it, or impersonates a known client with a localhost redirect) | Consent is deny-by-default and needs an owner session plus CSRF token. The screen names the client id, whether its name is self-declared (DCR), the redirect host, and warns for loopback redirects. Redirect URIs must match the registered ones exactly (loopback port aside). | `test_oauth.py::test_consent_needs_a_session_and_csrf_and_deny_is_explicit`, `::test_unregistered_redirect_uri_is_never_redirected_to` |

## Residual risks (accepted for v1)

- A client vendor could change connector behavior, for example by auto-approving tool calls. The harness doesn't depend on client-side approval prompts; its own approvals are the control.
- An owner who taps Approve without reading. Mitigations: typed confirmation for T3, short previews that lead with the risk, and a "why this tier" line.
- Proxmox bugs, and API behavior that differs between versions. Mitigations: a version check at bootstrap and a live nested-PVE suite.
- Reads are permitted to any connected client. The owner chooses which clients connect.
