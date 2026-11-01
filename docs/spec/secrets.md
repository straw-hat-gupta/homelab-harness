# Secrets

> **Status: specification, partly implemented.** Implemented so far: the envelope encryption, the KEK providers and the kind models in `homelab_harness.secrets` (no persistence, CLI, grants or use modes yet). It was researched on 2026-11-01, and anything marked "(unverified)" came from secondary sources. This document extends [safety-model.md](safety-model.md) S9 and replaces the "vault" sketch in [architecture.md](architecture.md). Terms follow the [glossary](../../GLOSSARY.md).

## Goal

The owner keeps every credential the lab needs in one place: SSH keys, passwords, API tokens, Proxmox tokens, kubeconfigs, certificates. Any agent the owner chooses can **use** a credential for an allowed purpose **without the value entering the model's context**. Adding a secret is quick, and it never means pasting the value into a chat.

## Principles

1. **Agents get handles, never values.** A secret is referenced as `secret://<name>`. No MCP tool, resource or prompt returns a secret value. There is deliberately no `get_secret` tool.
2. **The harness does the work.** The safest way to use a secret is to let the harness perform the action that needs it. A grant names a use mode, and the modes are ranked by how much exposure they allow.
3. **Grants are explicit and narrow.** A secret is usable only through the grants the owner created. Each grant names a client, a mode, a scope (hosts, capabilities, commands) and an approval rule.
4. **Be honest about exposure.** A mode that lets a process read the value (env injection) is labelled *exposing*, needs T3 approval, and is never the default. Output masking reduces accidents. It is not a security boundary.
5. **Values never travel through chat.** Intake happens through the CLI, through an owner-authenticated page, or through MCP URL-mode elicitation. A model may *ask* for a secret, but only the owner can supply it, outside the model.

## Secret kinds

| Kind | Fields (encrypted) | Metadata (plain) | Typical modes |
|---|---|---|---|
| `ssh_key` | private key, passphrase (optional), certificate (optional) | public key, fingerprint, comment | `ssh-sign` |
| `password` | password | username, URL or host, notes | `broker` |
| `api_token` | token | header scheme (`Bearer`, `token`, custom header), allowed base URLs | `broker`, `http-inject` |
| `proxmox_token` | secret UUID | `user@realm!tokenid`, cluster, privilege tier, expiry | `broker` (proxmox capability) |
| `cloudflare_token` | token | account or zone scope, expiry | `broker` (cloudflare capability) |
| `github_token` | token | repos and permissions, expiry | `broker`, `http-inject` |
| `file` | file bytes (kubeconfig, certificate and key, `.env`) | filename, MIME type, size | `broker`, `file-mount` |
| `kv` | key → value map | key names | any, per key |
| `totp_seed` | seed (later) | issuer, account | `broker` (code generation only) |

Every secret also carries:
- `description` and `tags`;
- `source` (`local`, or an external reference such as `op://…`, `bao://…` or `sops://…`);
- `created_at`, `rotated_at`, `expires_at`, and `rotate_every` (which drives reminders);
- `version` (rotation creates a new version, and old versions are kept until purged).

Validation per kind:
- `ssh_key`: the private key must load as OpenSSH or PEM (PKCS#8 or traditional), with its passphrase if it has one. The public key and the fingerprint (`SHA256:` plus unpadded base64, as `ssh-keygen -l` prints it) are derived from it. Passphrase-protected keys in OpenSSH format are refused for now, because decrypting them needs `bcrypt`.
- `proxmox_token`: the secret must be a UUID, and the token id must be `user@realm!tokenid`.
- `api_token`: base URLs must not embed credentials, and the `header` scheme needs a header name.
- `file`: at most 1 MiB.
- `kv`: at least one key, with names matching `[A-Za-z_][A-Za-z0-9_.-]*`.

Decrypted values are held in wrappers that print as `SecretValue(***)` and dump as `***`, can't be pickled, and give up the value only through `.reveal()`. Validation errors never echo the input. Every value is registered with the redactor as soon as it is wrapped. Text `file` contents are registered only up to 64 KiB.

## Use modes (ranked safest first)

| # | Mode | How it works | Who can see the value | Default approval |
|---|---|---|---|---|
| 1 | **`broker`** | A capability executor resolves the handle inside the harness, for example the Proxmox token in an API call or the GitHub PAT in the Obsidian capability. | The harness process only | Covered by the plan's own approval |
| 2 | **`ssh-sign`** | The harness holds the private key and signs. Harness executors sign in process. External agents use `hh ssh-agent`, a local agent socket that forwards sign requests to the harness over the tailnet. The harness checks the destination host key (OpenSSH `session-bind@openssh.com` and destination constraints) against the grant's host list. A short-lived SSH certificate per job is a later option, signed by a CA the harness holds. | Nobody. The key never leaves the harness. | Per grant: `none`, `per-session` or `per-use` (ntfy) |
| 3 | **`http-inject`** | The agent calls a harness egress route, `https://harness/egress/<route>/<path>`, which forwards to an allowlisted upstream and adds the auth header. There is no TLS interception and no CA to trust. Routes pin the upstream base URL and the allowed methods and paths. The upstream response passes through the redaction scanner. | Nobody on the agent side | Per grant. Write methods (POST, PUT, PATCH, DELETE) default to `per-use`. |
| 4 | **`file-mount`** | For a harness-spawned process, such as a capability that runs `kubectl` or `tofu`: the file is written to a tmpfs path readable only by that process and deleted when it exits. | That process | Covered by the plan |
| 5 | **`env`** *(exposing)* | `hh run --grant <id> -- <cmd>` injects variables into a child process on the owner's workstation. The command is pinned by the grant: an absolute path to argv[0] plus optional argument patterns. Output is masked, including exact, base64 and URL-encoded forms. | **The process, and any agent able to steer it.** It can print the value. | **T3**, per session, and the grant must name the command |
| 6 | **`reveal`** | Shows the value to the **owner** in the CLI (`hh secret reveal`, after re-authenticating with a passkey) or in the later web UI. | The owner | Re-authentication. **Never available over MCP.** |

Complementary, outside the harness: Claude Code's sandbox can mask credentials, placing a sentinel in the sandbox and substituting the real value only for allowlisted hosts ([source](https://code.claude.com/docs/en/sandboxing)). `hh` can generate those settings from a grant, but the value then sits in the user-level Claude Code config. Treat that as the `env` exposure level for the workstation, though not for the model.

## Grants: "this agent may use this secret for this"

```toml
# Created with `hh secret grant`; stored in the DB; shown in `hh secret show <name>`
[[grant]]
secret   = "github-vault-pat"
client   = "claude-code@workstation"     # an OAuth client id from clients.md, or "harness" for executors
mode     = "http-inject"
route    = "github-api"                  # upstream https://api.github.com, methods GET, POST /repos/<owner>/<vault-repo>/**
approval = "per-use-for-writes"
expires  = "2026-12-31"

[[grant]]
secret   = "docker-01-deploy-key"
client   = "codex@workstation"
mode     = "ssh-sign"
hosts    = ["docker-01.tailnet"]         # matched against the session-bind host key recorded at first use
approval = "per-session"
```

Rules:
- **Creating, widening or extending a grant is an owner action** (CLI, or the UI later) at T2. Granting the `env` mode, or any grant to `client = "*"`, is T3. Models can't create grants. They can *request* one, which produces a plan for the owner (see intake below).
- Grants are checked on every use, and every use writes `audit_events(kind="secret.used", secret_id, grant_id, client_id, mode, target, plan_id or job_id)`. No value or size is recorded.
- `hh secret revoke <name>` disables every grant at once. `hh secret delete` crypto-shreds the secret by destroying its DEK.

## Adding secrets (owner intake)

| Path | When to use it | How it works |
|---|---|---|
| **CLI** | Day to day, from the terminal | `hh secret add <name> --kind api_token` prompts with hidden input and then asks for metadata. Variants: `--from-file ~/.kube/config`, `--stdin` (for piping from another manager), `--from-op op://Vault/Item/field`. |
| **Generate in place** | SSH keys, random passwords | `hh secret generate ssh_key docker-01-deploy` creates an ed25519 key inside the harness and prints **only the public key** plus the `authorized_keys` line, with an optional `from=` restriction. The private key is never shown to anyone. |
| **Guided kinds** | Proxmox, Cloudflare and GitHub tokens | `hh proxmox bootstrap` prints the `pveum` commands and then opens a hidden prompt for the resulting token secret. The Cloudflare and GitHub helpers name the exact permission set to create. |
| **Intake page** | From a phone, or when an agent asks | Served by the harness on the tailnet (`/secrets/new`). It requires an owner passkey session and offers a form per kind. Agents never get a link that bypasses login: the page checks that the session belongs to the owner. This one page is the only web surface in v1. |
| **MCP request** (URL-mode elicitation) | An agent needs a credential that doesn't exist | The agent calls `secrets.request(name, kind, purpose, suggested_scope)`. The harness answers with MCP **URL-mode elicitation** pointing at the intake page, prefilled with the request, plus an ntfy notification: "Claude Code asks for a Cloudflare token for DNS on example.com". The owner enters the value in the browser, so it never passes through the model or the MCP client ([spec](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation)). The agent then sees `secrets.list` show the new handle, plus a grant if the owner approved one. Clients without URL-mode support (unverified per client) receive the same link as text. |
| **Import** | Migrating from another manager | `hh secret import` reads from 1Password (`onepassword-sdk` service account), SOPS + age files, or OpenBao/Vault KV. Imported secrets keep a `source` reference and can stay **linked**, meaning they are resolved from the source on use and never copied. |

What agents can see: `secrets.list` and `secrets.describe` return names, kinds, metadata, grants that apply to the calling client, and expiry. They return no values, no lengths, and no hashes.

## Storage and encryption

- **Envelope encryption.**
  - Each secret version has a random 256-bit data key (DEK). The value is encrypted with AES-256-GCM using a 96-bit random nonce, with AAD = `hh-secret-v1|secret_id|version|kind`.
  - The DEK is wrapped by the key-encryption key (KEK), also with AES-GCM and its own random nonce, with AAD = `hh-dek-v1|kek_id|secret_id|version|kind`. A wrapped DEK therefore can't be moved to another record or relabelled with another KEK id.
  - `secret_id` (`[A-Za-z0-9._:-]`), `kind` (lower snake case) and `kek_id` (`[A-Za-z0-9._-]`) can't contain `|`, so the AAD is unambiguous.
  - The row stores `ciphertext`, `nonce`, `wrapped_dek`, `dek_nonce` and `kek_id`.
  - Tampering with any of these, or with the AAD fields, and using the wrong KEK all raise `SecretIntegrityError`.
  - The sealed plaintext is the kind's fields as JSON (`file` bytes base64-encoded). Kind-specific metadata stays plain.
  - The library is pyca `cryptography` (`AESGCM`). There is no custom crypto and no plaintext fallback, unlike v0.
- **KEK providers,** behind a pluggable `KeyProvider`:
  1. `systemd-creds`, TPM2-sealed when the host has a TPM;
  2. a keyring file owned by the service user with mode 0400, outside the DB volume. Any other mode (0600 included, so the harness can't rewrite its own KEK), another owner, or a symlink is refused;
  3. an environment variable (`HH_SECRETS_KEK`), **dev and test only**. It is refused when `HH_ENV=prod`, and `/readyz` reports `vault` as degraded.

  Every provider reads the same **keyring format**: one `kek_id:base64key` entry per line (commas also separate entries, for the env variable), newest first. The first entry is the current KEK, and older entries stay until every DEK has been rewrapped. Keys must be exactly 32 bytes, and ids must be unique. Keys load once at startup, and a configured provider that is missing, insecure or malformed stops startup with an owner-safe message (R-25).

  The KEK is never stored in Postgres.
- **Rotation:**
  - `hh vault rotate-kek` rewraps every DEK, without re-encrypting the values.
  - `hh secret rotate <name>` creates a new version, either from new input or regenerated for generated kinds.
  - Grants follow the latest version.
- **Backups.** `pg_dump` contains only ciphertext. The KEK is backed up separately, and the docs give recovery steps. Restore drills are part of `hh doctor --deep`.
- **In memory.** Values are decrypted just in time, held as `bytes` (or `bytearray` where practical) for the shortest scope, and excluded from tracebacks. Both the structlog processor and the OTel processor mask every registered value.

**External backends:** an optional `SecretSource` interface with `resolve(ref) -> bytes` covers 1Password, OpenBao/Vault (v2.7.x), SOPS and Infisical. OpenBao is *not* embedded by default; it is optional, mainly for its SSH CA and dynamic secrets.

## Policy and tiers

| Action | Tier or rule |
|---|---|
| Use through `broker` or `file-mount` inside an approved plan | No extra approval |
| `ssh-sign` or `http-inject` use | Per grant: `none`, `per-session` or `per-use` (ntfy) |
| `env` use | T3, per session |
| Create a secret | Owner channels only (CLI, intake page) |
| Create or widen a grant | T2. T3 for the `env` mode or a wildcard client. |
| Reveal | Owner only, with passkey re-auth. Not available over MCP. Audited. |
| Delete or crypto-shred | T3, with typed name confirmation |
| A model calls `secrets.request` | Allowed. It creates a pending request for the owner, never a secret. |

## Leak defenses

- **Redaction scanner.** Every registered value, plus its base64, URL-encoded and hex forms, is masked in logs, spans, previews, errors, egress responses and `hh run` output.
- **Canary secret in tests.** The contract kit plants one per capability and asserts it never surfaces. A dedicated test covers the `http-inject` responses.
- **Expiry and rotation reminders** go to ntfy. `hh doctor` flags secrets that have expired, are unused for 90 days, or are over-granted (a grant broader than its observed use).
- **Steering** tells models never to ask for values in chat, and to use `secrets.request` instead ([steering.md](steering.md)).

## Roadmap placement

| Stage | Secrets work |
|---|---|
| 1 | Vault (envelope encryption, KEK providers, rotation); kinds `api_token`, `proxmox_token`, `password`, `kv`; CLI `add`, `list`, `rotate`, `revoke`; `broker` mode for capabilities; redaction scanner |
| 2 | Grants and audit, the intake page, and `secrets.request` with URL-mode elicitation plus the ntfy fallback |
| 3 | `ssh_key` with `generate`, in-process `ssh-sign` for the linux and docker capabilities, `hh ssh-agent` with destination checks, and `file-mount` |
| 5 | `http-inject` egress routes (GitHub, Cloudflare); imports from 1Password and SOPS |
| After v1 | `env` mode via `hh run`, an SSH CA with short-lived certificates, linked external sources, the web UI secrets page, and `totp_seed` |

## Open questions

1. Should `hh ssh-agent` run as a long-lived local daemon, or be started per terminal session? Proposal: per session, through `eval $(hh ssh-agent)`, with the agent bound to that session's OAuth token.
2. The Python implementation of the agent socket protocol. Neither asyncssh nor Paramiko has an agent server (unverified for asyncssh), so it's about 300 lines on top of `cryptography`. Get it reviewed, or wrap OpenSSH's `ssh-agent` with `ssh-add -h` constraints instead.
3. Which clients support URL-mode elicitation: claude.ai, Claude Code, ChatGPT, Codex (unverified). The text-link fallback is always sent.
