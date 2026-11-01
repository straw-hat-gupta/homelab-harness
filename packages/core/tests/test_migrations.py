import logging

import psycopg
import pytest
import structlog
from alembic import command
from alembic.script import ScriptDirectory

from homelab_harness.db.migrate import alembic_config, main
from homelab_harness.settings import get_settings


def _public_state(conninfo):
    with psycopg.connect(conninfo) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }
        triggers = {
            r[0]
            for r in conn.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal").fetchall()
        }
        functions = {
            r[0]
            for r in conn.execute(
                "SELECT proname FROM pg_proc WHERE proname = 'audit_events_reject_change'"
            ).fetchall()
        }
    return tables, triggers, functions


def test_upgrade_downgrade_round_trip(empty_database_url, libpq_url):
    config = alembic_config(empty_database_url)

    command.upgrade(config, "head")
    tables, triggers, functions = _public_state(libpq_url(empty_database_url))
    assert {"audit_events", "alembic_version"} <= tables
    assert {"audit_events_no_update_delete", "audit_events_no_truncate"} <= triggers
    assert functions == {"audit_events_reject_change"}

    command.downgrade(config, "base")
    tables, triggers, functions = _public_state(libpq_url(empty_database_url))
    assert tables == {"alembic_version"}
    assert not triggers
    assert not functions

    command.upgrade(config, "head")
    command.check(config)  # and the re-applied schema still matches the models


def test_models_and_migrations_agree(migrated_url):
    # `alembic check`: fails if a model change has no migration.
    command.check(alembic_config(migrated_url))


def test_one_head_only():
    heads = ScriptDirectory.from_config(alembic_config("postgresql://u@h/db")).get_heads()
    assert len(heads) == 1


@pytest.fixture
def env_database_url(monkeypatch):
    def set_url(url):
        if url is None:
            monkeypatch.delenv("HH_DATABASE_URL", raising=False)
        else:
            monkeypatch.setenv("HH_DATABASE_URL", url)
        get_settings.cache_clear()

    yield set_url
    get_settings.cache_clear()
    # main() configures process logging; leave none behind for other tests.
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


def test_migrate_command_is_idempotent_and_checks(migrated_url, env_database_url, libpq_url):
    env_database_url(migrated_url)
    main(["upgrade"])
    main(["check"])
    main(["current"])
    with psycopg.connect(libpq_url(migrated_url)) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchall() == [("0001",)]


def test_migrate_command_without_url_exits_cleanly(env_database_url):
    env_database_url(None)
    with pytest.raises(SystemExit, match="HH_DATABASE_URL is not set"):
        main(["upgrade"])


def test_migrate_command_never_echoes_a_bad_url(env_database_url):
    env_database_url("mysql://user:hunter2-secret@db/x")
    with pytest.raises(SystemExit) as excinfo:
        main(["upgrade"])
    assert "hunter2-secret" not in str(excinfo.value)
