"""Real subprocess/stdio fake. Never invokes Claude, a model or a target."""

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from homelab_harness.fixture import TOOL
from homelab_harness.runtime import VERSION
from homelab_harness.state import State

mode, *args = sys.argv[1:]


def event(value: dict[str, Any]) -> None:
    print(json.dumps(value), flush=True)


async def call(config: dict[str, Any]) -> None:
    """Use the real SDK and actual tool subprocess, not a scripted tool result."""
    async with stdio_client(StdioServerParameters(**config)) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=3) as session:
            await session.initialize()
            result = await session.call_tool("cluster_summary", {})
            if getattr(result, "is_error", True):
                raise RuntimeError("fixture failed")


def main() -> None:
    if args == ["--version"]:
        print(f"{'0.0.0' if mode == 'wrong_version' else VERSION} (Claude Code)")
        return
    if args == ["auth", "status"]:
        event({"loggedIn": True, "authMethod": "api_key" if mode == "api" else "claude.ai"})
        return
    if mode == "bad_json":
        print("secret-canary not json", flush=True)
        return
    session_id = args[-1]
    tools = [TOOL, "mcp__rogue__steal"] if mode == "unsafe" else [TOOL]
    event({"type": "system", "subtype": "init", "tools": tools, "session_id": session_id})
    cfg = json.loads(Path(args[args.index("--mcp-config") + 1]).read_text())
    config = cfg["mcpServers"]["hh_fixture"]
    if mode in ("hang", "orphan"):
        marker = Path(config["args"][-2]) / "heartbeat"
        code = (
            "import time, pathlib\n"
            f"p=pathlib.Path({str(marker)!r})\n"
            "while True:\n p.write_text('alive'); time.sleep(.05)\n"
        )
        subprocess.Popen([sys.executable, "-c", code])
        if mode == "orphan":
            return
        time.sleep(60)
        return
    if mode == "flood":
        print("x" * 100_000, flush=True)
        return
    if mode == "stderr_flood":
        sys.stderr.write("secret-canary" * 100_000)
        sys.stderr.flush()
        time.sleep(60)
        return
    if mode == "budget":
        state = State(Path(config["args"][-2]))
        for _ in range(3):
            state.fixture_call(run_id=config["args"][-1], valid=False)
        time.sleep(60)
        return
    if mode != "no_tool":
        config.pop("type")
        asyncio.run(call(config))
    event(
        {
            "type": "stream_event",
            "event": {"delta": {"type": "text_delta", "text": "Fixture answer"}},
        }
    )
    if mode == "no_result":
        return
    event(
        {
            "type": "result",
            "subtype": "error_max_turns" if mode == "turns" else "success",
            "is_error": mode == "turns",
            "session_id": session_id,
            "result": "Fixture answer",
        }
    )
    if mode == "exit_failure":
        print("secret-canary provider error", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
