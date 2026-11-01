"""Database URL handling (pure logic).

The URL carries the database password, so nothing here puts the URL into an
exception message: parse errors from SQLAlchemy quote the whole string.
"""

from __future__ import annotations

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from homelab_harness_sdk.errors import InvalidInput

_DRIVER = "postgresql+psycopg"
_ACCEPTED = frozenset({"postgres", "postgresql", "postgresql+psycopg"})


def parse_database_url(raw: str) -> URL:
    """Parse a Postgres URL and pin the psycopg 3 driver.

    ``postgres://`` and ``postgresql://`` are accepted because that is what
    most tools print; both mean psycopg 3 here, which serves both the async app
    engine and DBOS's sync engine.

    Args:
        raw: The configured URL, including credentials.

    Returns:
        The parsed URL with driver ``postgresql+psycopg``.

    Raises:
        InvalidInput: If the URL cannot be parsed, is not Postgres, or names no
            database. The message never contains the URL.
    """
    try:
        url = make_url(raw)
    except ArgumentError:
        raise InvalidInput("HH_DATABASE_URL is not a valid database URL") from None
    if url.drivername not in _ACCEPTED:
        raise InvalidInput("HH_DATABASE_URL must be a postgresql:// URL")
    if not url.database:
        raise InvalidInput("HH_DATABASE_URL must name a database")
    return url.set(drivername=_DRIVER)


def render_database_url(url: URL) -> str:
    """Render a parsed URL back to a connectable string, password included.

    Args:
        url: A URL from :func:`parse_database_url`.

    Returns:
        The full URL. Treat it as a secret.
    """
    return url.render_as_string(hide_password=False)
