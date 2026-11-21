"""Disposable SDK host: official bundled runtime, harness-owned deny-by-default policy."""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    SystemMessage,
)
from claude_agent_sdk.types import (
    HookContext,
    HookInput,
    SyncHookJSONOutput,
    ToolPermissionContext,
)

from homelab_harness.fixture import TOOL
from homelab_harness.runtime import INSTRUCTIONS, MAX_LINE_BYTES
from homelab_harness.state import ProofError, State


def bundled_cli() -> str:
    """Locate the official binary asset in the locked SDK wheel."""
    return str(files("claude_agent_sdk").joinpath("_bundled", "claude"))


class Policy:
    """Only the no-argument fixture may execute; native tools remain denied."""

    def __init__(self, state: State, run_id: str) -> None:
        self.state = state
        self.run_id = run_id

    async def before_tool(
        self, data: HookInput, _tool_id: str | None, _context: HookContext
    ) -> SyncHookJSONOutput:
        """Gate every tool attempt, including calls that skip can_use_tool."""
        if (
            data["hook_event_name"] == "PreToolUse"
            and data["tool_name"] == TOOL
            and data["tool_input"] == {}
            and self.state.active(self.run_id)
        ):
            return {}
        try:
            self.state.fixture_call(run_id=self.run_id, valid=False)
        except (OSError, sqlite3.Error, ProofError):
            pass
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "Stage 1A permits only the fixture tool.",
            }
        }

    async def permission(
        self, _name: str, _args: dict[str, Any], _context: ToolPermissionContext
    ) -> PermissionResultDeny:
        """Deny unresolved approvals; this callback alone is not an all-tool gate."""
        return PermissionResultDeny(message="Not authorized in Stage 1A.")


def options(*, config: Path, session_id: str, resume: bool, policy: Policy) -> ClaudeAgentOptions:
    """Supply explicit SDK configuration; keep vendor-native tools under our policy."""
    return ClaudeAgentOptions(
        cli_path=bundled_cli(),
        cwd=Path.cwd(),
        system_prompt=INSTRUCTIONS,
        mcp_servers=config,
        strict_mcp_config=True,
        setting_sources=[],
        skills=[],
        permission_mode="default",
        allowed_tools=[TOOL],
        can_use_tool=policy.permission,
        hooks={
            "PreToolUse": [
                HookMatcher(
                    hooks=[policy.before_tool],
                    timeout=2,
                    on_failure="block",
                )
            ]
        },
        settings='{"autoMemoryEnabled":false,"disableClaudeAiConnectors":true}',
        include_partial_messages=True,
        max_turns=6,
        max_buffer_size=MAX_LINE_BYTES,
        session_id=None if resume else session_id,
        resume=session_id if resume else None,
        extra_args={"system-prompt-snapshot": "off", "disable-slash-commands": None},
    )


def emit(event: dict[str, Any]) -> None:
    """Emit only the session events needed by the parent, never provider error bodies."""
    print(json.dumps(event), flush=True)


async def serve(config: Path, session_id: str, resume: bool) -> None:
    """Drive supported SDK sessions; the SDK owns the Claude subprocess protocol."""
    cfg = json.loads(config.read_text())["mcpServers"]["hh_fixture"]
    state = State(Path(cfg["args"][-2]))
    policy = Policy(state, cfg["args"][-1])
    prompt = sys.stdin.read()
    async with ClaudeSDKClient(
        options=options(config=config, session_id=session_id, resume=resume, policy=policy)
    ) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            if isinstance(message, SystemMessage):
                emit({**message.data, "type": "system", "subtype": message.subtype})
            elif isinstance(message, StreamEvent):
                emit(
                    {
                        "type": "stream_event",
                        "session_id": message.session_id,
                        "event": message.event,
                    }
                )
            elif isinstance(message, AssistantMessage):
                emit({"type": "assistant", "message": {"usage": message.usage or {}}})
            elif isinstance(message, ResultMessage):
                emit(
                    {
                        "type": "result",
                        "subtype": message.subtype,
                        "is_error": message.is_error,
                        "session_id": message.session_id,
                        "result": message.result or "",
                    }
                )


def main() -> None:
    """Forward only native auth/version commands, or run the fixture SDK worker."""
    if sys.argv[1:] == ["--version"] or sys.argv[1:] in (
        ["auth", "status"],
        ["auth", "login"],
    ):
        os.execv(bundled_cli(), [bundled_cli(), *sys.argv[1:]])
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcp-config", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--session-id")
    group.add_argument("--resume")
    args = parser.parse_args()
    try:
        asyncio.run(serve(args.mcp_config, args.resume or args.session_id, args.resume is not None))
    except Exception:
        raise SystemExit("SDK run failed.") from None


if __name__ == "__main__":
    main()
