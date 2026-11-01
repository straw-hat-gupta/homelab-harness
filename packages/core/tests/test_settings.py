import pytest
from pydantic import ValidationError

from homelab_harness.settings import Environment, LogFormat, Settings


def test_defaults_are_safe_for_production():
    s = Settings()
    assert s.env is Environment.PROD
    assert s.host == "127.0.0.1"  # never bind publicly by default
    assert s.log_format is LogFormat.JSON


def test_reads_prefixed_environment(monkeypatch):
    monkeypatch.setenv("HH_PORT", "9090")
    monkeypatch.setenv("HH_ENV", "dev")
    s = Settings()
    assert s.port == 9090
    assert s.env is Environment.DEV


def test_dotenv_in_working_directory_is_ignored(tmp_path, monkeypatch):
    # R-24: a stray .env must not change behavior.
    (tmp_path / ".env").write_text("HH_PORT=1234\n")
    monkeypatch.chdir(tmp_path)
    assert Settings().port == 8080


def test_invalid_port_is_rejected(monkeypatch):
    monkeypatch.setenv("HH_PORT", "70000")
    with pytest.raises(ValidationError):
        Settings()
