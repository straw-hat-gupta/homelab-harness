"""``homelab-harness-token``: create, rotate, revoke and list client tokens.

Runs on the harness host (or in its container) against ``HH_DATABASE_URL``. The
token is printed once, on stdout, and only its hash is stored. ``--role owner``
creates the token ``hh`` uses for the owner API; the default role is ``mcp``.

MCP-role tokens are the legacy way in, accepted at ``/mcp`` only while
``HH_MCP_LEGACY_TOKENS`` is true; OAuth (ADR-0007) replaces them. ``list`` and
``revoke`` also cover OAuth clients (by the id ``list`` shows), so a lost
machine can be cut off from the host even when ``hh`` is not at hand.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from homelab_harness.auth.registry import list_all_clients, revoke_any_client
from homelab_harness.db.engine import create_engine, create_session_factory
from homelab_harness.db.url import parse_database_url
from homelab_harness.log_config import configure_logging
from homelab_harness.mcp.clients import ClientRole, create_client
from homelab_harness.redaction import redactor
from homelab_harness.settings import Settings, get_settings
from homelab_harness_sdk.errors import HarnessError

_PROG = "homelab-harness-token"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=_PROG, description="Manage client tokens (reads HH_DATABASE_URL)."
    )
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("create", help="register a client and print its token once")
    create.add_argument("--client", required=True, help="client id, for example claude-code")
    create.add_argument(
        "--rotate", action="store_true", help="replace the token of an existing client"
    )
    create.add_argument(
        "--role",
        choices=[r.value for r in ClientRole],
        default=ClientRole.MCP.value,
        help="mcp (an AI client, /mcp only) or owner (the hh CLI, /api only); default mcp",
    )
    revoke = sub.add_parser("revoke", help="revoke a client's token or an OAuth client's grants")
    revoke.add_argument("--client", required=True, help="an id as shown by list")
    sub.add_parser("list", help="list client tokens and OAuth clients")
    return parser


async def _run(settings: Settings, args: argparse.Namespace) -> str:
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine).begin() as session:
            match args.action:
                case "create":
                    return await create_client(
                        session,
                        client_id=args.client,
                        rotate=args.rotate,
                        role=ClientRole(args.role),
                    )
                case "revoke":
                    count = await revoke_any_client(
                        session, client_id=args.client, now=datetime.now(UTC)
                    )
                    return f"revoked {args.client} ({count})"
                case _:
                    rows = await list_all_clients(session)
                    lines = [
                        f"{r.id}\t{r.kind}\tcreated {r.created_at.isoformat()}\t"
                        + (f"active ({r.active})" if r.active else "revoked")
                        for r in rows
                    ]
                    return "\n".join(lines) or "no clients"
    finally:
        await engine.dispose()


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
    if args.action == "create":
        sys.stderr.write(
            f"Token for {args.client} (shown once; store it in your client's config):\n"
        )
    sys.stdout.write(output + "\n")


if __name__ == "__main__":  # pragma: no cover
    main()
