"""MCP client registrations and the homelab-harness-token command (real Postgres)."""

import logging
import uuid

import pytest
import structlog

from homelab_harness.mcp.clients import (
    TOKEN_PREFIX,
    ClientRole,
    client_for_token,
    create_client,
    list_clients,
    revoke_client,
)
from homelab_harness.mcp.token_cli import main
from homelab_harness.settings import get_settings
from homelab_harness_sdk.errors import Conflict, InvalidInput, NotFound


@pytest.fixture
def client_id():
    return f"cli-{uuid.uuid4().hex[:8]}"


async def test_create_verify_rotate_revoke(sessions, client_id):
    async with sessions.begin() as session:
        first = await create_client(session, client_id=client_id)
    assert first.startswith(TOKEN_PREFIX)
    assert len(first) > 40
    async with sessions() as session:
        assert await client_for_token(session, first) == client_id
    async with sessions.begin() as session:
        with pytest.raises(Conflict):
            await create_client(session, client_id=client_id)
    async with sessions.begin() as session:
        second = await create_client(session, client_id=client_id, rotate=True)
    async with sessions() as session:
        assert await client_for_token(session, first) is None
        assert await client_for_token(session, second) == client_id
    async with sessions.begin() as session:
        await revoke_client(session, client_id=client_id)
        await revoke_client(session, client_id=client_id)  # idempotent
    async with sessions() as session:
        assert await client_for_token(session, second) is None
        listed = {c.client_id: c for c in await list_clients(session)}
    assert listed[client_id].revoked_at is not None
    async with sessions.begin() as session:
        third = await create_client(session, client_id=client_id, rotate=True)
    async with sessions() as session:
        assert await client_for_token(session, third) == client_id


@pytest.mark.parametrize("bad", ["Claude Code", "", "-x", "a/b", "x" * 65])
async def test_client_ids_are_labels(sessions, bad):
    async with sessions.begin() as session:
        with pytest.raises(InvalidInput):
            await create_client(session, client_id=bad)


async def test_tokens_without_the_prefix_or_too_long_are_refused_without_a_query(sessions):
    async with sessions() as session:
        assert await client_for_token(session, "Bearer-ish") is None
        assert await client_for_token(session, TOKEN_PREFIX + "x" * 500) is None


async def test_revoking_an_unknown_client_is_not_found(sessions):
    async with sessions.begin() as session:
        with pytest.raises(NotFound):
            await revoke_client(session, client_id="never-registered")


@pytest.fixture
def env_database(monkeypatch, migrated_url):
    monkeypatch.setenv("HH_DATABASE_URL", migrated_url)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


def test_cli_prints_the_token_once_and_revokes(env_database, client_id, capsys):
    main(["create", "--client", client_id])
    out, err = capsys.readouterr()
    token = out.strip()
    assert token.startswith(TOKEN_PREFIX)
    assert "shown once" in err
    assert token not in err
    main(["list"])
    listing = capsys.readouterr().out
    assert client_id in listing
    assert token not in listing
    assert "active" in listing
    with pytest.raises(SystemExit, match="already exists"):
        main(["create", "--client", client_id])
    main(["revoke", "--client", client_id])
    assert f"revoked {client_id}" in capsys.readouterr().out


async def test_roles_are_disjoint_and_survive_rotation(sessions, client_id):
    async with sessions.begin() as session:
        owner = await create_client(session, client_id=client_id, role=ClientRole.OWNER)
    async with sessions() as session:
        assert await client_for_token(session, owner) is None  # the default role is mcp
        assert await client_for_token(session, owner, role=ClientRole.OWNER) == client_id
    async with sessions.begin() as session:
        with pytest.raises(Conflict, match="roles do not change"):
            await create_client(session, client_id=client_id, rotate=True)
    async with sessions.begin() as session:
        rotated = await create_client(
            session, client_id=client_id, rotate=True, role=ClientRole.OWNER
        )
    async with sessions() as session:
        assert await client_for_token(session, rotated, role=ClientRole.OWNER) == client_id
        listed = {c.client_id: c for c in await list_clients(session)}
    assert listed[client_id].role is ClientRole.OWNER


def test_cli_creates_owner_tokens(env_database, client_id, capsys):
    main(["create", "--client", client_id, "--role", "owner"])
    capsys.readouterr()
    main(["list"])
    assert f"{client_id}\towner\t" in capsys.readouterr().out


def test_cli_without_database_exits_cleanly(monkeypatch):
    monkeypatch.delenv("HH_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit, match="HH_DATABASE_URL is not set"):
            main(["list"])
    finally:
        get_settings.cache_clear()
