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
| T-06 | The public MCP endpoint is attacked (scanning, credential stuffing, OAuth abuse) | Only `/mcp` and the OAuth endpoints are public; the edge returns 404 for every other path. Vendor connectors can't complete an interactive Access login, so this hostname is the single default entry on `public_allowlist` ([cloudflare.md](capabilities/cloudflare.md)). It is protected by the harness's OAuth 2.1, plus an Access IP-allowlist policy for vendor egress ranges where the vendor publishes them (unverified per vendor). OAuth 2.1 with PKCE and resource indicators, single owner identity, short token lifetimes, rate limits. The REST API, ntfy callbacks and Grafana stay on the tailnet. | [clients.md](clients.md); a deploy test checking that only the allowlisted paths are routable through the tunnel |
| T-07 | Theft of an MCP access token (an attacker gets a client's token) | Tokens are scoped to the MCP resource, short-lived, and revocable from the CLI. A stolen token still cannot approve anything (S2). The worst case is reads and plan creation, and every plan is shown to the owner. | S2; token revocation tests |
| T-08 | Harness compromise (RCE in a dependency) | Least-privilege tokens bounded by target ACLs (S8). No root on Proxmox. The vault key lives in the environment or a file outside the DB. The app DB role cannot UPDATE or DELETE audit rows. Pinned and hashed deps, `pip-audit`, Renovate, SBOM. | S8, S9; CI supply-chain jobs |
| T-09 | Lockout: a network, firewall, SSH or ACL change cuts off access | These are T3 floors. A preflight lockout check asserts the harness IP and owner tailnet keep 8006/22. Network apply uses Proxmox's staged config with an auto-revert timer unless the owner confirms afterwards. | Safety floors; [proxmox.md](capabilities/proxmox.md) network section |
| T-10 | Wrong disk wiped (device names shift, `/dev/sdb` ≠ the disk the owner meant) | Disks are identified by `/dev/disk/by-id` plus serial. Preflight checks that the disk is empty (no partitions, signatures, mounts, or ZFS/LVM/Ceph membership). T3 typed confirmation of the serial suffix. | proxmox.md ZFS section; fixtures of non-empty disks |
| T-11 | Accidental public exposure of an internal service | Publishing a hostname without an Access policy is refused (floor). DNS and tunnel changes are T3. | [cloudflare.md](capabilities/cloudflare.md) |
| T-12 | Secrets leak into logs, traces, previews, errors or client context | Redaction processors in structlog and the OTel span processor. Tokens are never returned. The canary-secret contract test covers every capability. Provider error bodies are mapped to safe messages. | S9; the contract kit's redaction test |
| T-13 | Subscription ToS violation (account banned) | The harness never stores, relays or uses Claude/ChatGPT subscription credentials. Clients connect *to* the harness. Unattended automation invokes the owner's own unmodified CLIs on the owner's machine. | [clients.md](clients.md); ADR-0003 |
| T-14 | Approval channel spoofing (a fake ntfy callback) | Callback tokens are HMAC-signed, single-use and bound to the plan hash. The callback endpoint is tailnet-only. The ntfy topic has access control. | approvals tests |
| T-15 | Vault notes exfiltrated through a connected client | Path allowlist and size limits on note reads. The owner decides which clients connect. Note reads are audited. | [obsidian.md](capabilities/obsidian.md) |
| T-16 | Supply chain: a malicious package update (the 2026 LiteLLM-style incident) | Locked, hashed dependencies. No auto-merge of dependency updates. Minimal dependency set. A model gateway is not needed, because the harness calls no model. | CI |

## Residual risks (accepted for v1)

- A client vendor could change connector behavior, for example by auto-approving tool calls. The harness doesn't depend on client-side approval prompts; its own approvals are the control.
- An owner who taps Approve without reading. Mitigations: typed confirmation for T3, short previews that lead with the risk, and a "why this tier" line.
- Proxmox bugs, and API behavior that differs between versions. Mitigations: a version check at bootstrap and a live nested-PVE suite.
- Reads are permitted to any connected client. The owner chooses which clients connect.
