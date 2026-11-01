"""Alembic environment: run migrations over the async psycopg engine.

Loaded by Alembic only, through :func:`homelab_harness.db.migrate.alembic_config`,
which supplies the URL in ``config.attributes``.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

import homelab_harness.audit.models as audit_models
from homelab_harness.db.base import Base

# Importing a model module registers its tables on Base.metadata.
MODEL_MODULES = (audit_models,)

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    url = config.attributes.get("database_url")
    if not isinstance(url, str):
        raise RuntimeError("run migrations with homelab-harness-migrate, not the alembic CLI")
    return url


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    # NullPool: a migration run is one connection, closed when it ends.
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_online())
