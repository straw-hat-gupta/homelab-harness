"""Shared fixtures: one real Postgres per test session (testcontainers).

Services test against real Postgres, never a mocked store (R-01). Without
Docker the database tests are skipped with a clear reason, except in CI, where
a missing Docker daemon fails the run instead of silently skipping half the suite.
"""

import os
import uuid

import docker
import psycopg
import pytest
from alembic import command
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from testcontainers.community.postgres import PostgresContainer

from homelab_harness.db.engine import create_engine, create_session_factory
from homelab_harness.db.migrate import alembic_config
from homelab_harness.settings import Environment, Settings

POSTGRES_IMAGE = "postgres:17-alpine"


def _docker_problem():
    try:
        docker.from_env().ping()
    except Exception as exc:
        return type(exc).__name__
    return None


def _libpq_url(url):
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def libpq_url():
    """Convert a SQLAlchemy URL to one plain psycopg accepts (no driver suffix)."""
    return _libpq_url


@pytest.fixture(scope="session")
def postgres_url():
    problem = _docker_problem()
    if problem is not None:
        if os.environ.get("CI"):
            pytest.fail(f"Docker is required for the database tests in CI ({problem})")
        pytest.skip(f"Docker is unavailable ({problem}); database tests need it")
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def migrated_url(postgres_url):
    command.upgrade(alembic_config(postgres_url), "head")
    return postgres_url


@pytest.fixture
def empty_database_url(postgres_url):
    """A fresh, empty database in the shared container, dropped afterwards."""
    name = f"t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_libpq_url(postgres_url), autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    yield make_url(postgres_url).set(database=name).render_as_string(hide_password=False)
    with psycopg.connect(_libpq_url(postgres_url), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture
def db_settings(migrated_url):
    return Settings(env=Environment.TEST, database_url=SecretStr(migrated_url))


@pytest.fixture
async def engine(db_settings):
    eng = create_engine(db_settings)
    yield eng
    await eng.dispose()


@pytest.fixture
def sessions(engine):
    return create_session_factory(engine)
