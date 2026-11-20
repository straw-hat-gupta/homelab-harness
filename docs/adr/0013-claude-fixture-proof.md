# ADR-0013: Claude Agent SDK fixture proof before target access

- **Status:** selected implementation for Stage 1A, 2026-11-20; real runtime/guest acceptance pending.
- **Scope:** guest-local SDK adapter, one fixture tool, no lab credentials or network listener.

## Decision

Use Python 3.13, the official Claude Agent SDK 0.2.187 (bundled unmodified Claude Code 2.1.330), the official MCP Python SDK and standard-library process/JSON/SQLite/locking. The Agent SDK owns the native agent/control protocol, loop, auth and history. No custom inference loop or generic provider framework. The MCP SDK owns protocol framing. SQLite stores only local proof registration/audit/counters, not credentials or transcripts. No archived source/stack is restored.

The owner selected the Agent SDK instead of manually driving a restricted CLI. Do not use bare or restricted mode. Keep native tools in the runtime and apply deterministic harness policy. Stage 1A authorizes only the no-argument fixture; all native tools/unknown calls are denied. Permission mode is explicitly default, with only the fixture auto-allowed. An all-tool PreToolUse callback runs before normal permission evaluation, with a two-second timeout and on_failure=block. The SDK requires the native runtime to acknowledge failure-blocking support; unsupported/ignored hooks fail initialization. A deny-only can_use_tool callback handles unresolved approvals but is not assumed to see every call. Never enable bypassPermissions/acceptEdits/auto modes as a shortcut.

Pass setting_sources=[], no skills, explicit instructions, disabled auto memory, strict explicit MCP config and disabled Claude.ai connectors. These settings do not suppress administrator policy or all global inputs. Use a dedicated private guest/account; verify actual behavior with canaries. Native-tool authorization is separate from future OS isolation and target-secret brokerage, which remain unresolved before 1B.

Keep supported native login in the bundled binary, not a wrapper token cache/proxy. The first proof accepts native subscription metadata only; it does not silently select API billing. A fixed environment allowlist excludes inherited provider/cloud/proxy/token overrides. The explicit login entry delegates to Anthropic's auth command. Only wrapper-registered, confirmed UUID sessions for this pinned version can resume. Claude keeps its own transcript. Application audit is append-only and allowlisted; failed audit refuses tool output. One local OS lock prevents overlapping runs; stale runs are marked interrupted without replay.

Host the SDK in a disposable child. The outer controller enforces 120-second execution, 4096 request bytes, 64 KiB event lines and 1 MiB each of worker stdout/stderr. SDK max_turns=6; tool budget is 8 attempts with a stop after 3 denials. Version/auth checks each get 10 seconds. Cancellation revokes tool access, kills the inherited process group and closes pipes with bounded cleanup. The dedicated MCP child checks persisted expiry/status independently; it exits on expiry because SDK stdio may block in a reader thread. Actual native child behavior remains a manual gate.

Stop further work if reported input context exceeds 32,768 tokens including caches. This is retrospective, not a pre-inference token/cost quota; native compaction stays with Claude. Require a successful SDK terminal result, an audited fixture call and clean worker exit before reporting completion. Streaming text is partial until then. No target access until native hook/isolation/cancellation/subscription/history evidence is recorded by the owner.

## Sources and limits

Inspected the installed SDK/control implementation and bundled version without a model call. [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview), [official Python SDK](https://github.com/anthropics/claude-agent-sdk-python), [permissions](https://code.claude.com/docs/en/agent-sdk/permissions), [hooks](https://code.claude.com/docs/en/agent-sdk/hooks), [settings boundaries](https://code.claude.com/docs/en/agent-sdk/claude-code-features), [subscription support](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan), [conditions](https://code.claude.com/docs/en/legal-and-compliance). Subscription billing support is not blanket authorization to offer one's own Claude.ai login or intermediate other users' tokens. This is an owner-operated personal proof; redistribution/hosting conditions need a separate review when that scope exists.

This increment supplies a testable prototype, not Stage 1A acceptance. A failed safety check cannot be waived by calling a model answer successful. [Getting started](../getting-started.md) defines the owner-run gate.
