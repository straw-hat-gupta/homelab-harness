import base64
import os

import httpx
import pytest
from pydantic import SecretStr

from homelab_harness.app import create_app
from homelab_harness.health import CheckStatus
from homelab_harness.secrets.keys import (
    EnvKeyProvider,
    FileKeyProvider,
    KeyProviderError,
    SystemdCredsKeyProvider,
    build_key_provider,
    generate_kek,
    keyring_line,
    parse_keyring,
    vault_check,
)
from homelab_harness.settings import Environment, KekProviderKind, Settings


def _keyring(*ids):
    keks = [generate_kek(i) for i in ids]
    return keks, "\n".join(keyring_line(k) for k in keks) + "\n"


def _write(path, text, mode):
    path.write_text(text)
    os.chmod(path, mode)
    return path


def test_parse_keyring_newest_first_with_comments():
    keks, text = _keyring("kek-2", "kek-1")
    parsed = parse_keyring(f"# rotated 2026-11-01\n\n{text}", source="test")
    assert [k.kek_id for k in parsed] == ["kek-2", "kek-1"]
    assert [k.key for k in parsed] == [k.key for k in keks]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "no KEK entries"),
        ("# only a comment\n", "no KEK entries"),
        ("no-separator", "not kek_id:base64key"),
        ("k1:not base64!!", "not valid base64"),
        (f"k1:{base64.b64encode(b'short').decode()}", "32 bytes"),
        (f"bad id:{base64.b64encode(bytes(32)).decode()}", "KEK id"),
        (
            f"k1:{base64.b64encode(bytes(32)).decode()}\nk1:{base64.b64encode(bytes(32)).decode()}",
            "appears twice",
        ),
    ],
)
def test_parse_keyring_rejects_malformed_input(text, message):
    with pytest.raises(KeyProviderError, match=message):
        parse_keyring(text, source="test")


def test_parse_error_never_echoes_key_material():
    encoded = base64.b64encode(os.urandom(31)).decode()
    with pytest.raises(KeyProviderError) as info:
        parse_keyring(f"k1:{encoded}", source="test")
    assert encoded not in str(info.value)


def test_file_provider_accepts_owner_read_only(tmp_path):
    keks, text = _keyring("kek-2", "kek-1")
    provider = FileKeyProvider(_write(tmp_path / "kek", text, 0o400))
    assert provider.current() == keks[0]
    assert provider.get("kek-1") == keks[1]
    assert provider.kek_ids() == ("kek-2", "kek-1")
    assert provider.name == "file"


@pytest.mark.parametrize("mode", [0o600, 0o700, 0o440, 0o404, 0o644, 0o640, 0o604, 0o610])
def test_file_provider_refuses_any_mode_but_0400(tmp_path, mode):
    _, text = _keyring("kek-1")
    with pytest.raises(KeyProviderError, match="must be 0400"):
        FileKeyProvider(_write(tmp_path / "kek", text, mode))


def test_file_provider_refuses_a_file_owned_by_another_user(tmp_path, monkeypatch):
    _, text = _keyring("kek-1")
    path = _write(tmp_path / "kek", text, 0o400)
    owner = path.stat().st_uid
    if owner == 0:
        pytest.skip("running as root, which is always an accepted owner")
    monkeypatch.setattr(os, "geteuid", lambda: owner + 1)
    with pytest.raises(KeyProviderError, match="owned by uid"):
        FileKeyProvider(path)


def test_file_provider_refuses_symlinks_and_missing_files(tmp_path):
    _, text = _keyring("kek-1")
    real = _write(tmp_path / "kek", text, 0o400)
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(KeyProviderError, match="cannot be opened"):
        FileKeyProvider(link)
    with pytest.raises(KeyProviderError, match="does not exist"):
        FileKeyProvider(tmp_path / "missing")


def test_unknown_kek_id_raises(tmp_path):
    _, text = _keyring("kek-1")
    provider = FileKeyProvider(_write(tmp_path / "kek", text, 0o400))
    with pytest.raises(KeyProviderError, match="unknown KEK id"):
        provider.get("kek-0")


def test_systemd_provider_reads_credentials_directory(tmp_path):
    keks, text = _keyring("kek-1")
    _write(tmp_path / "hh-kek", text, 0o400)
    provider = SystemdCredsKeyProvider(credentials_directory=tmp_path, credential="hh-kek")
    assert provider.current() == keks[0]
    assert provider.name == "systemd-creds"


def test_systemd_provider_fails_clearly_without_credentials(tmp_path):
    with pytest.raises(KeyProviderError, match="CREDENTIALS_DIRECTORY is not set"):
        SystemdCredsKeyProvider(credentials_directory=None, credential="hh-kek")
    with pytest.raises(KeyProviderError, match="not loaded"):
        SystemdCredsKeyProvider(credentials_directory=tmp_path, credential="hh-kek")
    with pytest.raises(KeyProviderError, match="plain file name"):
        SystemdCredsKeyProvider(credentials_directory=tmp_path, credential="../etc/kek")


def test_env_provider_accepts_comma_separated_entries():
    keks, _ = _keyring("kek-2", "kek-1")
    provider = EnvKeyProvider(",".join(keyring_line(k) for k in keks), env=Environment.DEV)
    assert provider.kek_ids() == ("kek-2", "kek-1")


def test_env_provider_is_refused_in_prod():
    _, text = _keyring("kek-1")
    with pytest.raises(KeyProviderError, match="not prod"):
        EnvKeyProvider(text, env=Environment.PROD)


def test_build_key_provider_from_settings(tmp_path, monkeypatch):
    assert build_key_provider(Settings()) is None
    _, text = _keyring("kek-1")
    path = _write(tmp_path / "kek", text, 0o400)
    monkeypatch.setenv("HH_SECRETS_KEK_PROVIDER", "file")
    monkeypatch.setenv("HH_SECRETS_KEK_FILE", str(path))
    assert isinstance(build_key_provider(Settings()), FileKeyProvider)
    monkeypatch.setenv("HH_SECRETS_KEK_PROVIDER", "systemd-creds")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("HH_SECRETS_KEK_CREDENTIAL", "kek")
    assert isinstance(build_key_provider(Settings()), SystemdCredsKeyProvider)


@pytest.mark.parametrize(
    ("provider", "message"),
    [
        (KekProviderKind.FILE, "HH_SECRETS_KEK_FILE is unset"),
        (KekProviderKind.ENV, "HH_SECRETS_KEK is unset"),
        (KekProviderKind.SYSTEMD_CREDS, "CREDENTIALS_DIRECTORY is not set"),
    ],
)
def test_build_key_provider_fails_clearly_when_incomplete(provider, message):
    settings = Settings(env=Environment.DEV, secrets_kek_provider=provider)
    with pytest.raises(KeyProviderError, match=message):
        build_key_provider(settings)


async def test_vault_check_ok_for_file_and_degraded_for_env(tmp_path):
    _, text = _keyring("kek-1")
    file_result = await vault_check(FileKeyProvider(_write(tmp_path / "kek", text, 0o400)))()
    assert file_result.status is CheckStatus.OK
    assert file_result.detail == "file provider, current KEK kek-1, 1 key(s)"
    env_result = await vault_check(EnvKeyProvider(text, env=Environment.TEST))()
    assert env_result.status is CheckStatus.DEGRADED
    assert "dev and test only" in env_result.detail


def _env_settings(env, text):
    return Settings(env=env, secrets_kek_provider=KekProviderKind.ENV, secrets_kek=SecretStr(text))


async def test_app_registers_vault_check_when_configured():
    keks, text = _keyring("kek-1")
    app = create_app(_env_settings(Environment.TEST, text))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/readyz")).json()
    assert body["checks"]["vault"]["status"] == "degraded"
    assert base64.b64encode(keks[0].key).decode() not in str(body)


def test_app_without_provider_has_no_vault_check():
    app = create_app(Settings(env=Environment.TEST))
    assert app.state.key_provider is None


def test_app_startup_fails_with_env_provider_in_prod():
    _, text = _keyring("kek-1")
    with pytest.raises(KeyProviderError, match="not prod"):
        create_app(_env_settings(Environment.PROD, text))
