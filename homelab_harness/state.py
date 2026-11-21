"""Private SQLite metadata and append-only audit, never conversation content."""

import fcntl
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

Outcome = Literal["running", "succeeded", "failed", "interrupted"]


class ProofError(Exception):
    """An owner-safe error code, without provider bodies or input values."""


def private_directory(path: Path) -> None:
    """Create a private directory; refuse unsafe existing state."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ProofError("State directory must be owned by you with mode 0700.")


class State:
    """Single-owner proof metadata. Not a credential vault or transcript store."""

    def __init__(self, directory: Path) -> None:
        private_directory(directory)
        self.directory = directory
        self.path = directory / "proof.sqlite3"
        self.lock_path = directory / "active.lock"
        for path in (self.path, self.lock_path):
            if path.is_symlink() or (
                path.exists() and (path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077)
            ):
                raise ProofError("State files must be private, owned files.")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, version TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, outcome TEXT NOT NULL,
                    deadline REAL NOT NULL, calls INTEGER NOT NULL DEFAULT 0,
                    failures INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS audit (
                    sequence INTEGER PRIMARY KEY, run_id TEXT NOT NULL, at TEXT NOT NULL,
                    event TEXT NOT NULL CHECK(event IN
                        ('started','succeeded','failed','interrupted','fixture_ok','fixture_denied'))
                );
                CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
                    BEGIN SELECT RAISE(ABORT, 'append only'); END;
                CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
                    BEGIN SELECT RAISE(ABORT, 'append only'); END;
            """)

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection]:
        """Open the actual store with a short lock deadline."""
        db = sqlite3.connect(self.path, timeout=1)
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def exclusive(self) -> Generator[None]:
        """Refuse overlapping wrappers; a process crash releases the OS lock."""
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ProofError("Another proof is active.") from exc
            with self.connect() as db:
                for (run_id,) in db.execute(
                    "SELECT id FROM runs WHERE outcome IN ('running', 'stopping')"
                ):
                    self._event(db, run_id, "interrupted")
                db.execute(
                    "UPDATE runs SET outcome='interrupted' WHERE outcome IN ('running', 'stopping')"
                )
            yield
        finally:
            os.close(fd)

    @staticmethod
    def _event(db: sqlite3.Connection, run_id: str, event: str) -> None:
        db.execute(
            "INSERT INTO audit(run_id, at, event) VALUES (?, ?, ?)",
            (run_id, datetime.now(UTC).isoformat(), event),
        )

    def start(
        self, *, run_id: str, session_id: str, version: str, resume: bool, seconds: float
    ) -> None:
        """Register only wrapper-owned sessions and a fresh bounded run."""
        with self.connect() as db:
            if resume:
                row = db.execute(
                    "SELECT version, confirmed FROM sessions WHERE id=?", (session_id,)
                ).fetchone()
                if row != (version, 1):
                    raise ProofError(
                        "Resume requires a confirmed session from this runtime version."
                    )
            else:
                db.execute("INSERT INTO sessions(id, version) VALUES (?, ?)", (session_id, version))
            db.execute(
                "INSERT INTO runs(id, session_id, outcome, deadline) VALUES (?, ?, 'running', ?)",
                (run_id, session_id, datetime.now(UTC).timestamp() + seconds),
            )
            self._event(db, run_id, "started")

    def confirm(self, session_id: str) -> None:
        """Record the native session ID only after a validated initialization event."""
        with self.connect() as db:
            db.execute("UPDATE sessions SET confirmed=1 WHERE id=?", (session_id,))

    def finish(self, run_id: str, outcome: Outcome) -> None:
        """Commit the outcome before reporting it to the owner."""
        with self.connect() as db:
            db.execute("UPDATE runs SET outcome=? WHERE id=?", (outcome, run_id))
            self._event(db, run_id, outcome)

    def stop_tools(self, run_id: str) -> None:
        """Revoke the ephemeral tool server before cleaning up detached processes."""
        with self.connect() as db:
            db.execute("UPDATE runs SET outcome='stopping' WHERE id=?", (run_id,))

    def fixture_call(self, *, run_id: str, valid: bool) -> bool:
        """Atomically budget and audit a call before any fixture result is returned."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT outcome, deadline, calls, failures FROM runs WHERE id=?", (run_id,)
            ).fetchone()
            if row is None:
                return False
            outcome, deadline, calls, failures = row
            allowed = (
                valid
                and outcome == "running"
                and deadline > datetime.now(UTC).timestamp()
                and calls < 8
                and failures < 3
            )
            db.execute(
                "UPDATE runs SET calls=calls+1, failures=failures+? WHERE id=?",
                (int(not allowed), run_id),
            )
            self._event(db, run_id, "fixture_ok" if allowed else "fixture_denied")
            return allowed

    def check_budget(self, run_id: str) -> None:
        """Stop the outer run after exhausted tool budgets, including invalid calls."""
        with self.connect() as db:
            row = db.execute("SELECT calls, failures FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None or row[0] > 8 or row[1] >= 3:
                raise ProofError("Tool-call or repeated-failure limit reached.")

    def active(self, run_id: str) -> bool:
        """Bound a tool server even when its parent or cancellation channel is lost."""
        with self.connect() as db:
            row = db.execute("SELECT outcome, deadline FROM runs WHERE id=?", (run_id,)).fetchone()
            return bool(row and row[0] == "running" and row[1] > datetime.now(UTC).timestamp())
