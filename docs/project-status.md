# Project status

Reviewed 2026-11-20. **Stage 1A fixture prototype is implemented; real Claude/VM acceptance is pending.** No Stage 1 acceptance box is complete. No Proxmox access, Mac client, listening service, installer, vault, GUI or supervisor exists in the restarted implementation.

The [vision](spec/vision.md) and [Stage 1 contract](stage-1.md) remain: a thin Mac client will connect to a service guest running an official agent runtime. The vendor runtime owns its loop/authentication/history; the harness owns lab context, tools and deterministic authorization.

## Current evidence

The launcher hosts the Claude Agent SDK in a bounded child process, with its unmodified bundled CLI. The harness uses a fail-closed all-tool hook and a fallback permission callback; 1A permits only one invented-data MCP tool. Native tools remain part of the runtime, under that policy, without bare/restricted mode. SQLite holds session registration and payload-free run/audit metadata. Tests cover fake worker processes, actual MCP stdio/SQLite, tool-policy decisions, limits, failures and child cancellation.

Vendor docs, SDK source/configuration and binary version metadata were inspected. No paid inference, subscription login, live Claude tool use/history, Ubuntu installation or Proxmox read was verified. Fixture/policy tests do not prove effective native or OS isolation. Context usage is checked retrospectively, not capped before inference. Exact evidence is in [validation](validation.md).

## Historical implementation

The complete [snapshot](code-reuse.md#preserved-source), commit `a97f2aa`, preserves the earlier MCP-first service, CLI, encrypted vault, authentication/OAuth, audit, 18 read tools, DBOS foundation, observability and React UI. Its results do not describe this restart. No old source was restored.

## Next

The owner is preparing the dedicated VM. Review this increment, follow [getting started](getting-started.md), and record actual subscription/tool/stream/resume/isolation/stop evidence. Resolve failures at 1A before 1B or a real target credential. The required later [hosting-node recovery](future.md#required-later-harness-host-availability) remains outside Stage 1.
