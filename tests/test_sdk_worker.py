import asyncio
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk.types import (
    HookContext,
    PreToolUseHookInput,
    SyncHookJSONOutput,
    ToolPermissionContext,
)

from homelab_harness.fixture import TOOL
from homelab_harness.sdk_worker import Policy, bundled_cli, options
from tests.test_state import started


def attempt(name: str, args: dict[str, Any]) -> PreToolUseHookInput:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "fixture-session",
        "transcript_path": "/unused",
        "cwd": "/unused",
        "tool_name": name,
        "tool_input": args,
        "tool_use_id": "fixture-call",
    }


def assert_denied(result: SyncHookJSONOutput) -> None:
    specific = result.get("hookSpecificOutput")
    assert specific is not None and specific["hookEventName"] == "PreToolUse"
    assert specific.get("permissionDecision") == "deny"


@pytest.mark.parametrize("name", ["Bash", "Read", "Write", "WebFetch", "Agent", "unknown"])
def test_native_tools_denied_before_permission_callback(tmp_path: Path, name: str) -> None:
    state, run_id = started(tmp_path)
    policy = Policy(state, run_id)
    result = asyncio.run(
        policy.before_tool(
            attempt(name, {"command": "secret-canary"}), None, HookContext(signal=None)
        )
    )
    assert_denied(result)
    assert "secret-canary" not in str(result)
    permission = asyncio.run(policy.permission(name, {}, ToolPermissionContext()))
    assert permission.behavior == "deny"
    with state.connect() as db:
        assert "secret-canary" not in str(db.execute("SELECT * FROM audit").fetchall())


def test_fixture_policy_and_fail_closed_options(tmp_path: Path) -> None:
    state, run_id = started(tmp_path)
    policy = Policy(state, run_id)
    assert asyncio.run(policy.before_tool(attempt(TOOL, {}), None, HookContext(signal=None))) == {}
    assert_denied(
        asyncio.run(
            policy.before_tool(attempt(TOOL, {"extra": "denied"}), None, HookContext(signal=None))
        )
    )
    cfg = options(config=tmp_path / "mcp.json", session_id="fixture", resume=False, policy=policy)
    assert cfg.cli_path == bundled_cli() and Path(bundled_cli()).is_file()
    assert cfg.tools is None  # Native tools exist, but policy above denies them.
    assert cfg.setting_sources == [] and cfg.strict_mcp_config and cfg.skills == []
    assert cfg.permission_mode == "default" and cfg.allowed_tools == [TOOL]
    assert cfg.can_use_tool == policy.permission
    assert cfg.hooks is not None
    assert cfg.hooks["PreToolUse"][0].on_failure == "block"
    assert cfg.hooks["PreToolUse"][0].timeout == 2
    assert "restricted" not in cfg.extra_args and "bare" not in cfg.extra_args
    state.stop_tools(run_id)
    assert_denied(
        asyncio.run(policy.before_tool(attempt(TOOL, {}), None, HookContext(signal=None)))
    )
