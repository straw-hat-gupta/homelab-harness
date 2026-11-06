"""``homelab-harness-owner``: enroll the owner and manage recovery codes, on the harness host.

Host access is the root of trust: whoever can run this against
``HH_DATABASE_URL`` is the owner. There is no web registration.

* ``enroll`` creates the owner, prints a one-time passkey enrollment link
  (valid 15 minutes) and ten recovery codes. It refuses once an owner is
  enrolled: there is only one.
* ``enroll --add-passkey`` prints a link that adds a passkey to the owner.
* ``recovery-codes`` replaces all recovery codes with ten new ones.

Links and codes go to stdout only, once; only hashes are stored.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from homelab_harness.audit.service import AuditWriter
from homelab_harness.auth.config import auth_config
from homelab_harness.auth.owner import OwnerService
from homelab_harness.db.engine import create_engine, create_session_factory
from homelab_harness.db.url import parse_database_url
from homelab_harness.log_config import configure_logging
from homelab_harness.redaction import redactor
from homelab_harness.settings import Settings, get_settings
from homelab_harness_sdk.errors import HarnessError

_PROG = "homelab-harness-owner"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=_PROG,
        description="Enroll the harness owner (reads HH_DATABASE_URL and HH_PUBLIC_URL).",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    enroll = sub.add_parser("enroll", help="print a one-time passkey enrollment link")
    enroll.add_argument(
        "--add-passkey",
        action="store_true",
        help="add another passkey to the enrolled owner (no new recovery codes)",
    )
    sub.add_parser("recovery-codes", help="replace every recovery code with ten new ones")
    return parser


async def _run(settings: Settings, args: argparse.Namespace) -> str:
    config = auth_config(settings)
    if config is None:
        raise HarnessError("HH_PUBLIC_URL is not set; it is the address the link must use")
    engine = create_engine(settings)
    try:
        sessions = create_session_factory(engine)
        service = OwnerService(sessions, config=config, audit=AuditWriter(sessions))
        if args.action == "recovery-codes":
            codes = await service.regenerate_recovery_codes()
            return _codes_text(codes)
        enrollment = await service.start_enrollment(add_passkey=args.add_passkey)
        lines = [
            "Open this link in a browser on the tailnet within 15 minutes "
            f"(until {enrollment.expires_at.isoformat(timespec='minutes')}):",
            "",
            f"  {enrollment.url}",
        ]
        if enrollment.recovery_codes:
            lines += ["", _codes_text(enrollment.recovery_codes)]
        return "\n".join(lines)
    finally:
        await engine.dispose()


def _codes_text(codes: list[str]) -> str:
    return "\n".join(
        [
            "Recovery codes (each works once; print or store them offline, they are shown once):",
            "",
            *(f"  {c}" for c in codes),
        ]
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Run one action; exit non-zero with an owner-safe message on failure.

    Args:
        argv: Arguments without the program name; ``sys.argv[1:]`` when omitted.
    """
    args = _parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings)
    if settings.database_url is None:
        sys.exit(f"{_PROG}: HH_DATABASE_URL is not set")
    try:
        password = parse_database_url(settings.database_url.get_secret_value()).password
        if password:
            redactor.register(password)
        output = asyncio.run(_run(settings, args))
    except HarnessError as exc:
        sys.exit(f"{_PROG}: {exc.safe_message}")
    sys.stdout.write(output + "\n")


if __name__ == "__main__":  # pragma: no cover
    main()
