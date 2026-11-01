"""Schema migrations: the Alembic config and the ``homelab-harness-migrate`` command.

The migration scripts ship inside the package (``homelab_harness/migrations``), so
the container image can migrate itself. The URL comes from ``HH_DATABASE_URL``
through :class:`~homelab_harness.settings.Settings`; there is no ``alembic.ini``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError

from homelab_harness.db.url import parse_database_url, render_database_url
from homelab_harness.log_config import configure_logging
from homelab_harness.redaction import redactor
from homelab_harness.settings import get_settings
from homelab_harness_sdk.errors import InvalidInput

# Date-prefixed revision files sort in creation order in a directory listing.
_FILE_TEMPLATE = "%%(year)d%%(month).2d%%(day).2d_%%(rev)s_%%(slug)s"


def alembic_config(database_url: str) -> Config:
    """Build an Alembic config for the packaged migrations.

    Args:
        database_url: Postgres URL, any accepted scheme.

    Returns:
        A config whose ``env.py`` connects to ``database_url``. The URL is passed
        through ``attributes``, not the ini options, so ``%`` in a password needs
        no escaping and the URL never lands in a config file.
    """
    config = Config()
    config.set_main_option("script_location", "homelab_harness:migrations")
    config.set_main_option("file_template", _FILE_TEMPLATE)
    config.attributes["database_url"] = render_database_url(parse_database_url(database_url))
    return config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="homelab-harness-migrate",
        description="Migrate the harness database (reads HH_DATABASE_URL).",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    up = sub.add_parser("upgrade", help="apply migrations (default: to head)")
    up.add_argument("revision", nargs="?", default="head")
    down = sub.add_parser("downgrade", help="revert to a revision ('-1', 'base', or an id)")
    down.add_argument("revision")
    sub.add_parser("current", help="show the applied revision")
    sub.add_parser("check", help="fail if the models and the migrations disagree")
    rev = sub.add_parser("revision", help="create a migration script (developers)")
    rev.add_argument("-m", "--message", required=True)
    rev.add_argument("--autogenerate", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run one migration action and exit non-zero on failure.

    Args:
        argv: Arguments without the program name; ``sys.argv[1:]`` when omitted.
    """
    args = _parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings)
    if settings.database_url is None:
        sys.exit("homelab-harness-migrate: HH_DATABASE_URL is not set")
    try:
        url = parse_database_url(settings.database_url.get_secret_value())
    except InvalidInput as exc:
        sys.exit(f"homelab-harness-migrate: {exc.safe_message}")
    if url.password:
        redactor.register(url.password)
    config = alembic_config(render_database_url(url))
    try:
        match args.action:
            case "upgrade":
                command.upgrade(config, args.revision)
            case "downgrade":
                command.downgrade(config, args.revision)
            case "current":
                command.current(config)
            case "check":
                command.check(config)
            case _:
                command.revision(config, message=args.message, autogenerate=args.autogenerate)
    except CommandError as exc:
        # Alembic's messages name revisions and differences, never the URL.
        sys.exit(f"homelab-harness-migrate: {exc}")


if __name__ == "__main__":  # pragma: no cover
    main()
