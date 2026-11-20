"""Guest-local owner entry point; not the future Mac hh client."""

import argparse
import asyncio
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from homelab_harness.runtime import MAX_PROMPT_BYTES, Settings, child_environment, run
from homelab_harness.state import ProofError


def main() -> None:
    """Launch one explicit subscription-backed fixture request without lab access."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", help="Native session UUID printed by a previous proof run")
    parser.add_argument(
        "--login", action="store_true", help="Open the bundled CLI's own login flow"
    )
    args = parser.parse_args()
    os.umask(0o077)
    settings = Settings(
        directory=Path.home() / ".local/share/homelab-harness-proof",
        environment=child_environment(os.environ),
    )
    if args.login:
        if args.resume:
            parser.error("--login and --resume cannot be combined")
        raise SystemExit(
            subprocess.call(
                [*settings.command, "auth", "login"], env=settings.environment, cwd=Path.home()
            )
        )
    print("Fixture-only proof. This invokes your logged-in Claude subscription.", flush=True)
    print("Enter one request, then press Ctrl-D. Ctrl-C stops the whole run.", flush=True)
    try:
        raw = sys.stdin.buffer.read(MAX_PROMPT_BYTES + 1)
        prompt = raw.decode("utf-8")
        session = asyncio.run(run(settings, prompt, resume=args.resume, emit=_emit))
    except KeyboardInterrupt:
        raise SystemExit("\nInterrupted; no request was automatically replayed.") from None
    except (ProofError, OSError, sqlite3.Error, ValueError, TimeoutError, ExceptionGroup) as exc:
        message = str(exc) if isinstance(exc, ProofError) else "Proof failed or reached its limit."
        print(
            f"\n{message} Any streamed text was partial; no successful run is recorded.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    print(f"\nCompleted fixture proof. Session: {session}")
    print("Resume: uv run python -m homelab_harness.proof --resume " + session)


def _emit(text: str) -> None:
    print(text, end="", flush=True)


if __name__ == "__main__":
    main()
