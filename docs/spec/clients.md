# Clients and managed runtimes

> **Status: binding target design; guest-local SDK fixture adapter only.** Mac connections and real runtime acceptance remain pending. See [Stage 1](../stage-1.md).

## Connections are different boundaries

| Connection | Purpose | Authentication owner |
|---|---|---|
| Mac CLI → harness instance | Select a cluster, configure owner settings, submit/observe/interrupt a session | Our private pairing and owner authorization |
| Service → official runtime | Launch, stream, resume and stop the actual program through a documented interface | Service process/runtime isolation |
| Runtime → model provider | Subscription login, inference, native conversation loop | Vendor runtime's supported flow/storage |
| Runtime → domain tools | Typed, scoped discovery calls | Restricted tool principal, never the owner principal |
| Tool service → Proxmox | Read cluster facts with target-enforced permissions | Protected read credential and verified target TLS |

Management and interaction both belong in `hh`. Management configures/checks connections and sessions; chat sends an owner task to the managed runtime. Neither permits the Mac to perform target I/O directly.

## Subscription integration

Launch the real, unmodified `claude` or `codex` program. Do not extract its OAuth tokens, implement a parallel vendor login/proxy, spoof a first-party client or pool subscriptions. Complete login through the runtime's supported browser/device/headless procedure, storing protected runtime state on the guest. A vendor login browser may run on the Mac without moving the agent there.

Prefer structured supported input/output/control over terminal-screen scraping. [ADR-0013](../adr/0013-claude-fixture-proof.md) selects the Claude Agent SDK and its bundled official binary for 1A. The SDK owns its protocol/loop; our outer process controller owns lifetime/output and deterministic hooks own tool authorization. No bare/restricted mode is used. Codex App Server remains a later candidate. Verify actual login, instructions, tool policy, streaming, continuation and interruption on the guest. See [vendor evidence](../adr/0012-managed-agent-runtime-and-cli-first-stages.md#vendor-evidence-and-limits); availability/terms/limits may change and no universal subscription guarantee is made.

## Saved instances

Save only alias, address, expected stable server/cluster identity and a reference to protected client authentication. Show the verified instance before chat. New or changed identity requires explicit trust; never route a saved session or secret to another instance solely because the alias matches. Multiple profiles need fixture isolation tests, not multi-cluster orchestration.

Select one authenticated encrypted private transport before 1C. SSH forwarding and explicitly trusted HTTPS are proposals, not dual implementations to build. LAN presence alone is not authentication. Revocation must terminate access, including new messages on an existing session/stream. Public listeners, remote web clients and external-client registration are out of scope.

## Local inference later

The model is not the whole runtime. A raw model endpoint proposes tool calls; an existing runtime must drive them. Codex documents local providers, so local inference need not cause us to implement a loop. Model location (Mac, lab node, VPS) and runtime location (service guest) are separate. Verify each model/runtime's tools and context handling before offering it.

## Authority

The model cannot invoke owner setup, secret intake, access widening, approval or tool installation through its tool principal. Native runtime shell/filesystem/network capabilities must not bypass that boundary. Configuration flags and prompts alone are not proof; 1A must demonstrate effective restrictions and the secret isolation described by [secrets.md](secrets.md).
