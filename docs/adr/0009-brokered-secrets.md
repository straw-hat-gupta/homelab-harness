# ADR-0009: Built-in vault with brokered use: agents get handles, never values

- **Status:** accepted (2026-11-01)

## Context

The owner wants any chosen agent (Claude Code, Codex, claude.ai, ChatGPT, or the harness's own executors) to use SSH keys, passwords and tokens without seeing them, and wants adding secrets to be easy. Research on 2026-11-01 found the following:
- Env-injection tools (`op run`, `doppler run`) expose values to the process, and so to any agent able to steer it. Output masking can be bypassed.
- Credential-injecting proxies and agent brokers (Infisical Agent Vault, Aembit, CyberArk Secretless) are mostly in preview or beta, or aimed at enterprises.
- OpenSSH agent destination constraints let a signer refuse hosts outside an allowed set.
- MCP 2026-07-28 requires URL-mode elicitation for sensitive input, so the value never passes through the model or the client.

## Decision

- Build a small vault into the harness:
  - envelope encryption with AES-256-GCM, one DEK per secret version;
  - a KEK from systemd-creds/TPM or an age file, never stored in Postgres;
  - rotation by rewrapping.
- Agents reference secrets as `secret://<name>`. No MCP surface returns a value.
- Use goes through **grants** (client, mode, scope, approval, expiry), in modes ranked by exposure:
  1. `broker`
  2. `ssh-sign`
  3. `http-inject`
  4. `file-mount`
  5. `env` (exposing, T3)
  6. `reveal` (owner only)
- Intake goes through the CLI, generation inside the harness (SSH keys: only the public key is shown), a passkey-protected intake page on the tailnet, and `secrets.request` using MCP URL-mode elicitation with an ntfy notification.
- External managers (1Password, OpenBao/Vault, SOPS, Infisical) are optional `SecretSource` backends. They are not required.

Details are in [secrets.md](../spec/secrets.md).

## Alternatives rejected

- **Embedding OpenBao as the default.** It brings unseal and operations burden that a single-owner lab doesn't need. It is still supported as an optional backend, mainly for SSH certificates and dynamic secrets.
- **1Password or Bitwarden as the required store.** It adds an external dependency and a cost. Bitwarden Secrets Manager's self-hosted version is enterprise-only.
- **Env injection as the main mode.** It doesn't meet "agents can't see the value".

## Consequences

- The harness owns security-critical code (AEAD use, agent-protocol signing, egress routing). Each piece gets focused tests, R-34 to R-37, and a review before Stage 3.
- The intake page is the one small web surface in v1. It is tailnet-only and passkey-authenticated.
