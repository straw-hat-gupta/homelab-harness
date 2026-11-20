# Onboarding

> **Status: binding target design; not implemented.** No installer or `hh` setup command exists in the active repository.

Initial scope is a manually prepared dedicated service guest. Automatic creation/configuration of that guest is deferred. The operator need not install an agent or collector on each Proxmox node.

## Planned sequence

1. Choose and manually prepare the service guest. Record which node hosts it and what persistence is backed up. Supported guest/install method remains a 1A decision.
2. Install one unmodified official agent runtime. Guide its supported subscription login and retain its protected state on the guest.
3. Prove instructions, a harmless fixture tool, streaming, continuation, bounded stopping and native-tool isolation before supplying a target credential.
4. Configure one Proxmox endpoint, expected cluster identity and verified TLS trust. Confirm trust through a trusted owner channel; never disable verification.
5. Supply a read-only target credential through owner-only hidden intake. It stays in the broker; the runtime gets a handle/tool, not a value. Reuse an appropriate existing read token or show a separately reviewed identity-setup procedure. Do not create write tiers, pools or collectors automatically.
6. Run deterministic discovery and compare it with Proxmox. Report insufficient permissions precisely; never escalate automatically or rename/reorganize existing lab resources.
7. Pair the Mac using one encrypted authenticated private transport. Save the instance connection and reference to client access, not provider or Proxmox credentials.
8. Open the interactive session and complete the Stage 1 questions, restart/reconnect checks and acceptance record.

Re-running setup must show existing configuration and a proposed difference rather than overwrite it, replace encryption keys or duplicate an identity. Losing access cannot trigger silent token generation. A fresh Mac client can reconnect to existing service-side history.

## Boundaries

Read-only discovery never mutates targets. Creating a guest, changing ACLs or installing node software is a separate owner action outside this initial read path, with explicit effects shown first. Future automated mutations must satisfy the safety model; they cannot be hidden inside onboarding.

No broad profile inference is required initially. Owner notes may record conventions, but model guesses are not silently accepted as defaults or permission. Credentials are never entered in chat or command-line arguments. Backups of encrypted records and their encryption key must be separate; demonstrate recovery before depending on them.

The new setup flow and its exact commands will be documented increment by increment after implementation. See [getting started](../getting-started.md) for current status and [Stage 1](../stage-1.md) for gates.
