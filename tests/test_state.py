import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from homelab_harness.runtime import VERSION
from homelab_harness.state import ProofError, State


def started(tmp_path: Path, seconds: float = 60) -> tuple[State, str]:
    state = State(tmp_path / "private")
    run_id = str(uuid4())
    state.start(
        run_id=run_id, session_id=str(uuid4()), version=VERSION, resume=False, seconds=seconds
    )
    return state, run_id


def test_exclusive_lock_and_crash_recovery(tmp_path: Path) -> None:
    state, run_id = started(tmp_path)
    with state.exclusive():
        with pytest.raises(ProofError), State(state.directory).exclusive():
            pass
    with state.connect() as db:
        assert db.execute("SELECT outcome FROM runs WHERE id=?", (run_id,)).fetchone() == (
            "interrupted",
        )
        assert db.execute("SELECT event FROM audit ORDER BY sequence").fetchall() == [
            ("started",),
            ("interrupted",),
        ]


def test_budget_expiry_and_append_only_audit(tmp_path: Path) -> None:
    state, run_id = started(tmp_path)
    for _ in range(8):
        assert state.fixture_call(run_id=run_id, valid=True)
    assert not state.fixture_call(run_id=run_id, valid=True)
    with pytest.raises(ProofError):
        state.check_budget(run_id)
    with state.connect() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM audit")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE audit SET event='failed'")
    expired, expired_id = started(tmp_path / "expired", seconds=-1)
    assert not expired.fixture_call(run_id=expired_id, valid=True)
    assert not expired.active(expired_id)


def test_private_state_refuses_symlinks_and_open_permissions(tmp_path: Path) -> None:
    state = State(tmp_path / "private")
    state.directory.chmod(0o755)
    with pytest.raises(ProofError):
        State(state.directory)
    state.directory.chmod(0o700)
    state.path.unlink()
    state.path.symlink_to(tmp_path / "outside")
    with pytest.raises(ProofError):
        State(state.directory)


def test_repeated_failures_stop_even_after_valid_call(tmp_path: Path) -> None:
    state, run_id = started(tmp_path)
    for _ in range(3):
        assert not state.fixture_call(run_id=run_id, valid=False)
    assert not state.fixture_call(run_id=run_id, valid=True)
    with pytest.raises(ProofError):
        state.check_budget(run_id)
