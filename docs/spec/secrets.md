# Secrets and credential custody

> **Status: binding protections; no vault is implemented on this branch.** These requirements preserve the previous secrecy, encryption, grant and exposure boundaries. They may only be strengthened. Archived vault code is a [reuse candidate](../code-reuse.md), not a requirement to adopt its entire platform.

## Separate credentials

- **Provider login:** the unmodified official runtime completes and owns its supported subscription authentication. The wrapper must not extract its credential cache, export it into model context, proxy it or substitute custom inference calls. Model-directed filesystem/tools cannot read its protected state.
- **Proxmox read credential:** trusted tool-side code uses it inside the broker. It is inaccessible to the agent runtime's model-directed tools and never stored on the Mac.
- **Mac client access:** a revocable owner connection credential or existing authenticated transport. It does not confer permission on the model and is not interchangeable with target/provider credentials.

Every permission check uses a stable principal/instance/target identity. A label, local network or hidden filename is insufficient protection. Refuse use without a matching owner-created grant and audit each use.

## No value through the agent

Agents get handles such as `secret://pve-read`, not values. No tool, resource, prompt, result, error, preview, trace or audit exposes a secret value, its length or its hash. Public SSH keys/fingerprints can be deliberately public metadata; they do not expose the private half. Metadata must not carry secret values.

Owner intake uses hidden input outside chat, rejects secrets passed as command-line arguments and never echoes validation input. No model can create/widen a grant, approve a request or supply its own approval. The model may request missing access, but only the owner can supply it outside the conversation. Setup does not silently create broader target access.

Secret kinds and inputs must be typed and validated before storage/use. Do not register placeholder/empty credentials or accept mismatched token identity and secret metadata. Errors are owner-safe and never include provider bodies or credential-bearing URLs.

## Storage requirements

When implementing/reusing the vault, preserve its envelope-encryption guarantees:

- Random 256-bit data key per secret version. AES-256-GCM encryption with a random 96-bit nonce; authenticated data binds format version, secret identity, version and kind.
- Wrap each data key under a separate AES-GCM key-encryption key with its own nonce and authenticated data binding the encryption-key ID, secret identity/version/kind. IDs/encodings must be unambiguous. Tampering, wrong keys and moved/relabeled records fail closed.
- Use maintained cryptographic libraries; no invented cryptography, plaintext fallback or token-in-source shortcut.
- The encryption key stays outside encrypted-record/database backups. A production key comes from a protected file (0400, expected trusted owner, no symlink) or system credential facility. Environment-key mode is development/test only and visibly degraded; production refuses it.
- Missing, malformed, insecure or incorrect key configuration fails startup/secret resolution safely. No unconfigured-vault fallback for a real target credential.
- Keys rotate by rewrapping data keys, without re-encrypting values. Secrets rotate by version. Interrupted rewrap is recoverable/idempotent; do not discard old keys until all required records have been rewrapped and verified.
- Back up keys separately from encrypted records and demonstrate recovery. Re-running setup must not replace an existing key. Deleting encrypted live rows does not erase old WAL/backups; any crypto-shred claim must explain key/backup limitations.
- Decrypt only in the trusted operation's scope for the shortest practical lifetime. Printable/serialized wrappers mask values; exceptions do not echo them. Do not claim perfect zeroization in a managed runtime.

The persistence backend is not selected by these requirements. Its real boundary must be tested, and adopting the old store requires making its database/auth/migration dependencies explicit.

## Grants and exposure modes

Grants name principal, instance, secret, purpose, use mode, target/route/command scope, expiry and owner approval requirements. Check them on every use. Creating, widening or extending a grant is an owner-only T2 action; wildcard or environment-exposing grants are T3. Revocation blocks further use, including cached resolutions; rotating a revoked secret must not silently restore an unrelated grant.

Stage 1 supports only brokered target reads. Other previously designed modes remain excluded initially and cannot be enabled without their retained protections:

| Future mode | Required boundary |
|---|---|
| SSH signing | Private key stays with signer; verify destination host-key/session binding and grant. No unrestricted forwarding. |
| HTTP credential injection | Explicit upstream/method/path allowlist, no interception/global proxy, redacted response and per-use approval for writes by default. |
| Temporary file mount | Only the approved process can read the file; private temporary storage, deletion and cleanup on exit/failure. |
| Environment injection | Exposing to the process/agent; T3 per session, pinned command and arguments. Never a default or a substitute for brokered use. |
| Owner reveal | Owner-only reauthentication (the prior contract requires passkey reauthentication); audited; never a model tool or MCP result. |

In-process/approved-plan credential use does not create a second approval requirement, but does not bypass the plan's authorization. Deletion/crypto-shred requires owner T3 typed-name confirmation. A later secret-intake page must require authenticated owner access; an agent link cannot bypass login. External secret sources/imports are deferred and must retain narrow grants, custody and redaction.

## Leak verification

Mask registered values and relevant encoded forms (base64, URL-encoded and hex) across logs, traces, previews, errors, egress and tool output. Redaction is defense in depth, not a security boundary. Canary tests must cover every enabled surface, including failures, with target content canaries as well as secret values. Test that model-directed runtime tools cannot read protected target/provider files or use owner-only endpoints.

Native history/transcripts may contain private lab facts and therefore need private storage, explicit retention and safe export. They must never contain raw target credentials. Do not commit memory/transcripts, copy them to Git mirrors or log them as payloads automatically. [Testing/evals](testing-and-evals.md) defines the proof required before lab access.
