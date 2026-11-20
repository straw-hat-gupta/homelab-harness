"""One harmless stdio MCP tool, with no target adapter or network requests."""

import argparse
import asyncio
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from homelab_harness.state import ProofError, State

TOOL = "mcp__hh_fixture__cluster_summary"


def server(state: State, run_id: str) -> Server[dict[str, Any]]:
    """Build a fixed tool registry; caller arguments cannot choose authority."""

    async def list_tools(
        _ctx: ServerRequestContext[dict[str, Any]], _params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="cluster_summary",
                    description="Return invented cluster data for a boundary test.",
                    input_schema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                )
            ]
        )

    async def call_tool(
        _ctx: ServerRequestContext[dict[str, Any]], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        try:
            allowed = state.fixture_call(
                run_id=run_id, valid=params.name == "cluster_summary" and not params.arguments
            )
        except (OSError, sqlite3.Error, ProofError):
            allowed = False
        if not allowed:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="Fixture call refused.")],
                is_error=True,
            )
        data: dict[str, Any] = {
            "source": "invented-fixture-only",
            "as_of": datetime.now(UTC).isoformat(),
            "untrusted_data": {"cluster": "fixture-cluster", "nodes": ["fixture-node-a"]},
        }
        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(data))])

    return Server("hh-fixture", version="0.1.0", on_list_tools=list_tools, on_call_tool=call_tool)


async def serve(directory: Path, run_id: str) -> None:
    """Serve only over inherited stdio, never a listening network socket."""
    state = State(directory)
    app = server(state, run_id)

    async def expiry() -> None:
        monotonic_deadline = asyncio.get_running_loop().time() + 120
        try:
            while asyncio.get_running_loop().time() < monotonic_deadline and state.active(run_id):
                state.check_budget(run_id)
                await asyncio.sleep(0.1)
        except (OSError, sqlite3.Error, ProofError):
            os._exit(1)
        # SDK stdio can block in a stdin reader thread; terminate this dedicated child.
        os._exit(0)

    async with stdio_server() as (reader, writer):
        tasks = [
            asyncio.create_task(app.run(reader, writer, app.create_initialization_options())),
            asyncio.create_task(expiry()),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def main() -> None:
    """Private subprocess entry point; no owner/provider credentials in arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("run_id")
    args = parser.parse_args()
    try:
        asyncio.run(serve(args.directory, args.run_id))
    except (OSError, sqlite3.Error, ProofError):
        raise SystemExit("Fixture unavailable.") from None


if __name__ == "__main__":
    main()
