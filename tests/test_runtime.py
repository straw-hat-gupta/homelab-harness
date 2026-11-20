import asyncio
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from homelab_harness.fixture import TOOL
from homelab_harness.runtime import Events, Settings, child_environment, command, run, terminal_text
from homelab_harness.state import ProofError, State


def settings(tmp_path: Path, mode: str = "ok", seconds: float = 8) -> Settings:
    return Settings(
        directory=tmp_path / "private",
        environment={**child_environment(os.environ), "PYTHONPATH": str(Path.cwd())},
        command=(
            sys.executable,
            str(Path("tests/fake_claude.py").resolve()),
            mode,
        ),
        seconds=seconds,
    )


def test_real_stdio_stream_and_registered_resume(tmp_path: Path) -> None:
    output: list[str] = []
    cfg = settings(tmp_path)
    session = asyncio.run(run(cfg, "fixture please", resume=None, emit=output.append))
    assert output == ["Fixture answer"]
    assert asyncio.run(run(cfg, "again", resume=session, emit=output.append)) == session
    with State(cfg.directory).connect() as db:
        assert db.execute("SELECT outcome FROM runs").fetchall() == [("succeeded",)] * 2
        assert db.execute("SELECT event FROM audit WHERE event='fixture_ok'").fetchall() == [
            ("fixture_ok",),
            ("fixture_ok",),
        ]
        assert "fixture please" not in str(db.execute("SELECT * FROM audit").fetchall())


@pytest.mark.parametrize(
    "mode",
    [
        "api",
        "wrong_version",
        "bad_json",
        "unsafe",
        "flood",
        "stderr_flood",
        "no_tool",
        "no_result",
        "turns",
        "exit_failure",
        "budget",
    ],
)
def test_failure_never_records_success(tmp_path: Path, mode: str) -> None:
    cfg = settings(tmp_path, mode)
    with pytest.raises((ProofError, ValueError)) as error:
        asyncio.run(run(cfg, "fixture please", resume=None, emit=lambda _: None))
    assert "secret-canary" not in str(error.value)
    with State(cfg.directory).connect() as db:
        assert not db.execute("SELECT 1 FROM runs WHERE outcome='succeeded'").fetchone()


@pytest.mark.parametrize("resume", [str(uuid4()), "not-a-uuid", "../../other-history"])
def test_foreign_session_refused(tmp_path: Path, resume: str) -> None:
    with pytest.raises(ProofError):
        asyncio.run(run(settings(tmp_path), "continue", resume=resume, emit=lambda _: None))


@pytest.mark.parametrize("mode", ["hang", "orphan"])
def test_deadline_stops_children_even_after_parent_exit(tmp_path: Path, mode: str) -> None:
    cfg = settings(tmp_path, mode, seconds=1.5)
    with pytest.raises(TimeoutError):
        asyncio.run(run(cfg, "fixture", resume=None, emit=lambda _: None))
    marker = cfg.directory / "heartbeat"
    before = marker.stat().st_mtime_ns
    time.sleep(0.2)
    assert marker.stat().st_mtime_ns == before
    with State(cfg.directory).connect() as db:
        assert db.execute("SELECT outcome FROM runs").fetchone() == ("interrupted",)


def test_cancellation_stops_children(tmp_path: Path) -> None:
    cfg = settings(tmp_path, "hang")

    async def cancel() -> None:
        task = asyncio.create_task(run(cfg, "fixture", resume=None, emit=lambda _: None))
        async with asyncio.timeout(5):
            while not (cfg.directory / "heartbeat").exists():
                await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())
    marker = cfg.directory / "heartbeat"
    before = marker.stat().st_mtime_ns
    time.sleep(0.2)
    assert marker.stat().st_mtime_ns == before


@pytest.mark.parametrize("prompt", [" ", "x" * 4097, "é" * 2049])
def test_input_limit(tmp_path: Path, prompt: str) -> None:
    with pytest.raises(ProofError):
        asyncio.run(run(settings(tmp_path), prompt, resume=None, emit=lambda _: None))
    assert not (tmp_path / "private").exists()


def test_controls_exclude_api_environment_and_restricted_mode(tmp_path: Path) -> None:
    env = child_environment(
        {
            "HOME": "/home/test",
            "PATH": "/bin",
            "ANTHROPIC_API_KEY": "canary",
            "CLAUDE_CODE_OAUTH_TOKEN": "canary",
            "HTTPS_PROXY": "canary",
        }
    )
    assert "canary" not in env.values()
    args = command(
        settings(tmp_path), config=tmp_path / "mcp.json", session_id=str(uuid4()), resume=False
    )
    assert "--restricted" not in args
    assert "--bare" not in args
    assert terminal_text("\x1b]0;title\x07\rhello\n") == "]0;titlehello\n"


def test_context_and_session_stream_validation() -> None:
    session = str(uuid4())
    events = Events(session, lambda _: None)
    with pytest.raises(ProofError):
        events.accept(json.dumps({"type": "result"}).encode())
    events.accept(json.dumps({"type": "system", "subtype": "init", "tools": [TOOL]}).encode())
    with pytest.raises(ProofError):
        events.accept(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"usage": {"input_tokens": 1, "cache_read_input_tokens": 32_768}},
                }
            ).encode()
        )
    with pytest.raises(ProofError):
        events.accept(json.dumps({"type": "result", "session_id": str(uuid4())}).encode())
