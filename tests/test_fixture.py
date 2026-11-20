import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from tests.test_state import started


def test_real_mcp_schema_validation_audit_and_failure(tmp_path: Path) -> None:
    state, run_id = started(tmp_path)

    async def exercise() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "homelab_harness.fixture", str(state.directory), run_id],
            env={**os.environ, "PYTHONPATH": str(Path.cwd())},
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer, read_timeout_seconds=3) as client:
                await client.initialize()
                tools = await client.list_tools()
                assert [tool.name for tool in tools.tools] == ["cluster_summary"]
                assert tools.tools[0].input_schema["additionalProperties"] is False
                result = await client.call_tool("cluster_summary", {})
                assert isinstance(result, types.CallToolResult) and not result.is_error
                block = result.content[0]
                assert isinstance(block, types.TextContent)
                data = json.loads(block.text)
                assert data["source"] == "invented-fixture-only"
                assert data["as_of"].endswith("+00:00")
                for name, args in [
                    ("unknown-secret-canary", {}),
                    ("cluster_summary", {"secret": "canary"}),
                ]:
                    denied = await client.call_tool(name, args)
                    assert isinstance(denied, types.CallToolResult) and denied.is_error
                    assert "canary" not in str(denied)
                with state.connect() as db:
                    db.execute("""CREATE TRIGGER fail_audit BEFORE INSERT ON audit
                        BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END;""")
                denied = await client.call_tool("cluster_summary", {})
                assert isinstance(denied, types.CallToolResult) and denied.is_error

    asyncio.run(exercise())
    with state.connect() as db:
        rows = db.execute("SELECT * FROM audit").fetchall()
        assert "canary" not in str(rows)
        assert len(rows) == 4


def test_expired_tool_server_exits_without_parent_cancellation(tmp_path: Path) -> None:
    state, run_id = started(tmp_path, seconds=0.2)

    async def exercise() -> None:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "homelab_harness.fixture",
            str(state.directory),
            run_id,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        async with asyncio.timeout(3):
            assert await process.wait() == 0
        assert process.stdin is not None
        process.stdin.close()
        await process.stdin.wait_closed()

    asyncio.run(exercise())
