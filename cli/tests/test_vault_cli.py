"""``hh secret`` and ``hh vault`` against a respx-mocked owner API."""

import base64
import json
import secrets
import uuid

import httpx
import pytest
import respx
from typer.testing import CliRunner

from homelab_harness_cli.main import app

runner = CliRunner()
BASE = "http://harness.test"


@pytest.fixture(autouse=True)
def owner_env(monkeypatch):
    monkeypatch.setenv("HH_CLI_URL", BASE)
    monkeypatch.setenv("HH_CLI_TOKEN", f"hhmcp_{secrets.token_urlsafe(8)}")
    monkeypatch.delenv("HH_CLI_TOKEN_FILE", raising=False)


@pytest.fixture
def canary():
    return f"CANARY_CLI_{secrets.token_hex(10)}"


@pytest.fixture
def api():
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


def secret_json(name="pve", kind="password", version=1, **extra):
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "handle": f"secret://{name}",
        "kind": kind,
        "description": "",
        "tags": [],
        "source": "local",
        "metadata": {},
        "created_at": "2026-11-01T00:00:00Z",
        "rotated_at": None,
        "expires_at": None,
        "rotate_every_seconds": None,
        "revoked_at": None,
        "current_version": version,
        "versions": [],
    } | extra


def sent(route):
    return json.loads(route.calls.last.request.content)


def test_add_prompts_hidden_and_never_prints_the_value(api, canary):
    route = api.post("/api/secrets").mock(return_value=httpx.Response(201, json=secret_json()))
    result = runner.invoke(
        app,
        ["secret", "add", "pve", "--kind", "password", "--meta", "username=root"],
        input=f"{canary}\n{canary}\n",
    )
    assert result.exit_code == 0, result.output
    assert canary not in result.output
    assert "stored secret://pve (version 1)" in result.output
    body = sent(route)
    assert body["value"] == canary
    assert body["metadata"] == {"username": "root"}
    assert route.calls.last.request.headers["Authorization"].startswith("Bearer hhmcp_")


def test_add_refuses_a_mismatched_confirmation(api, canary):
    route = api.post("/api/secrets")
    result = runner.invoke(
        app, ["secret", "add", "pve", "--kind", "password"], input=f"{canary}\nother\n" * 3
    )
    assert result.exit_code != 0
    assert not route.called
    assert canary not in result.output


def test_add_from_stdin_and_from_file(api, canary, tmp_path):
    route = api.post("/api/secrets").mock(return_value=httpx.Response(201, json=secret_json()))
    result = runner.invoke(
        app,
        ["secret", "add", "pve", "--kind", "proxmox_token", "--stdin", "--meta-json", '{"a": 1}'],
        input=canary + "\n",
    )
    assert result.exit_code == 0, result.output
    assert sent(route)["value"] == canary
    assert sent(route)["metadata"] == {"a": 1}
    path = tmp_path / "token"
    path.write_text(canary + "\r\n")
    result = runner.invoke(
        app, ["secret", "add", "pve", "--kind", "api_token", "--from-file", str(path)]
    )
    assert result.exit_code == 0, result.output
    assert sent(route)["value"] == canary
    assert canary not in result.output


def test_add_kv_from_prompts_and_from_lines(api, canary):
    route = api.post("/api/secrets").mock(return_value=httpx.Response(201, json=secret_json()))
    result = runner.invoke(
        app,
        ["secret", "add", "env", "--kind", "kv", "--key", "A", "--key", "B"],
        input=f"{canary}\n{canary}\nsecond-value\nsecond-value\n",
    )
    assert result.exit_code == 0, result.output
    assert sent(route)["fields"] == {"values": {"A": canary, "B": "second-value"}}
    result = runner.invoke(
        app,
        ["secret", "add", "env", "--kind", "kv", "--stdin"],
        input=f"# comment\nA={canary}\n\nB=x=y\n",
    )
    assert result.exit_code == 0, result.output
    assert sent(route)["fields"] == {"values": {"A": canary, "B": "x=y"}}
    assert canary not in result.output


def test_add_file_sends_base64_and_its_name(api, tmp_path, canary):
    route = api.post("/api/secrets").mock(return_value=httpx.Response(201, json=secret_json()))
    path = tmp_path / "kubeconfig"
    path.write_bytes(canary.encode() + b"\x00\xff")
    result = runner.invoke(
        app, ["secret", "add", "kube", "--kind", "file", "--from-file", str(path)]
    )
    assert result.exit_code == 0, result.output
    body = sent(route)
    assert base64.b64decode(body["fields"]["content"]) == canary.encode() + b"\x00\xff"
    assert body["metadata"] == {"filename": "kubeconfig"}


@pytest.mark.parametrize(
    "argv",
    [
        ["secret", "add", "pve", "--kind", "password", "--value", "{c}"],
        ["secret", "add", "pve", "{c}", "--kind", "password"],
        ["secret", "add", "pve", "--kind", "password", "--password={c}"],
        ["secret", "rotate", "pve", "--value", "{c}"],
        ["secret", "rotate", "pve", "{c}"],
    ],
)
def test_values_on_the_command_line_are_refused_without_echo(api, canary, argv):
    result = runner.invoke(app, [a.format(c=canary) for a in argv])
    assert result.exit_code == 1
    assert "never taken from the command line" in result.output
    assert canary not in result.output
    assert not api.calls


def test_ssh_keys_need_a_file_or_stdin(api):
    result = runner.invoke(app, ["secret", "add", "k", "--kind", "ssh_key"])
    assert result.exit_code == 1
    assert "hh secret generate" in result.output
    assert not api.calls


def test_no_token_or_a_loose_token_file_is_refused(api, monkeypatch, tmp_path):
    monkeypatch.delenv("HH_CLI_TOKEN")
    result = runner.invoke(app, ["secret", "list"])
    assert result.exit_code == 1
    assert "--role owner" in result.output
    path = tmp_path / "token"
    path.write_text("hhmcp_x")
    path.chmod(0o644)
    monkeypatch.setenv("HH_CLI_TOKEN_FILE", str(path))
    result = runner.invoke(app, ["secret", "list"])
    assert result.exit_code == 1
    assert "chmod 0600" in result.output
    path.chmod(0o600)
    api.get("/api/secrets").mock(return_value=httpx.Response(200, json={"secrets": []}))
    result = runner.invoke(app, ["secret", "list"])
    assert result.exit_code == 0
    assert api.calls.last.request.headers["Authorization"] == "Bearer hhmcp_x"


def test_list_and_show_print_metadata(api):
    item = secret_json(
        name="pve-home-read",
        kind="proxmox_token",
        version=2,
        metadata={"token_id": "harness@pve!read"},
        versions=[
            {"version": 1, "kek_id": "kek-1", "created_at": "2026-10-01T00:00:00Z"},
            {"version": 2, "kek_id": "kek-1", "created_at": "2026-11-01T00:00:00Z"},
        ],
    )
    api.get("/api/secrets").mock(return_value=httpx.Response(200, json={"secrets": [item]}))
    api.get("/api/secrets/pve-home-read").mock(return_value=httpx.Response(200, json=item))
    listing = runner.invoke(app, ["secret", "list"])
    assert "pve-home-read" in listing.output
    assert "proxmox_token" in listing.output
    shown = runner.invoke(app, ["secret", "show", "pve-home-read"])
    assert "secret://pve-home-read  (proxmox_token, v2, active)" in shown.output
    assert "token_id:       harness@pve!read" in shown.output
    assert "version 2: 2026-11-01T00:00:00Z (KEK kek-1)" in shown.output


def test_rotate_reads_the_kind_then_prompts(api, canary):
    api.get("/api/secrets/pve").mock(return_value=httpx.Response(200, json=secret_json()))
    route = api.post("/api/secrets/pve/versions").mock(
        return_value=httpx.Response(200, json=secret_json(version=2))
    )
    result = runner.invoke(app, ["secret", "rotate", "pve"], input=f"{canary}\n{canary}\n")
    assert result.exit_code == 0, result.output
    assert sent(route) == {"value": canary, "metadata": None}
    assert "rotated secret://pve to version 2" in result.output
    assert canary not in result.output


def test_rotate_generate_prints_the_new_public_key(api):
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample deploy"
    route = api.post("/api/secrets/deploy/versions").mock(
        return_value=httpx.Response(
            200,
            json=secret_json(
                name="deploy", kind="ssh_key", version=2, metadata={"public_key": key}
            ),
        )
    )
    result = runner.invoke(app, ["secret", "rotate", "deploy", "--generate"])
    assert result.exit_code == 0, result.output
    assert sent(route) == {"generate": True, "metadata": None}
    assert key in result.output


def test_generate_prints_only_the_public_key(api):
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample deploy"
    route = api.post("/api/secrets/generate").mock(
        return_value=httpx.Response(
            201,
            json={
                "secret": secret_json(
                    name="deploy", kind="ssh_key", metadata={"fingerprint": "SHA256:abc"}
                ),
                "public_key": key,
                "authorized_keys": f'from="10.0.0.5" {key}',
            },
        )
    )
    result = runner.invoke(
        app,
        ["secret", "generate", "ssh_key", "deploy", "--comment", "deploy", "--from", "10.0.0.5"],
    )
    assert result.exit_code == 0, result.output
    assert sent(route)["from_hosts"] == ["10.0.0.5"]
    assert f'from="10.0.0.5" {key}' in result.output
    assert "SHA256:abc" in result.output
    assert runner.invoke(app, ["secret", "generate", "password", "x"]).exit_code == 1


def test_delete_needs_the_typed_name(api):
    route = api.delete("/api/secrets/pve").mock(
        return_value=httpx.Response(200, json={"name": "pve", "versions_destroyed": 2})
    )
    wrong = runner.invoke(app, ["secret", "delete", "pve"], input="pv\n")
    assert wrong.exit_code == 1
    assert not route.called
    right = runner.invoke(app, ["secret", "delete", "pve"], input="pve\n")
    assert right.exit_code == 0, right.output
    assert route.calls.last.request.url.params["confirm"] == "pve"
    assert "2 version(s) destroyed" in right.output
    flagged = runner.invoke(app, ["secret", "delete", "pve", "--confirm", "pve"])
    assert flagged.exit_code == 0


def test_revoke(api):
    route = api.post("/api/secrets/pve/revoke").mock(
        return_value=httpx.Response(200, json=secret_json())
    )
    result = runner.invoke(app, ["secret", "revoke", "pve"])
    assert result.exit_code == 0
    assert route.called


def test_rotate_kek_prints_counts_and_fails_on_failures(api):
    route = api.post("/api/vault/rotate-kek")
    route.mock(
        return_value=httpx.Response(
            200, json={"kek_id": "kek-2", "rewrapped": 3, "already_current": 1, "failed": 0}
        )
    )
    ok = runner.invoke(app, ["vault", "rotate-kek"])
    assert ok.exit_code == 0
    assert "current KEK kek-2: 3 rewrapped, 1 already current, 0 failed" in ok.output
    route.mock(
        return_value=httpx.Response(
            200, json={"kek_id": "kek-2", "rewrapped": 0, "already_current": 3, "failed": 1}
        )
    )
    assert runner.invoke(app, ["vault", "rotate-kek"]).exit_code == 1


def test_api_errors_show_the_harness_detail(api):
    api.get("/api/secrets/x").mock(
        return_value=httpx.Response(404, json={"detail": "no secret named 'x'"})
    )
    api.get("/api/secrets").mock(return_value=httpx.Response(401, json={"detail": "nope"}))
    missing = runner.invoke(app, ["secret", "show", "x"])
    assert missing.exit_code == 1
    assert "no secret named 'x'" in missing.output
    refused = runner.invoke(app, ["secret", "list"])
    assert refused.exit_code == 1
    assert "refused the owner token" in refused.output
    api.post("/api/secrets").mock(
        return_value=httpx.Response(
            422, json={"detail": [{"loc": ["body", "kind"], "msg": "bad kind", "type": "enum"}]}
        )
    )
    invalid = runner.invoke(app, ["secret", "add", "x", "--kind", "nope", "--stdin"], input="v\n")
    assert "body.kind: bad kind" in invalid.output


def test_unreachable_harness(api):
    api.get("/api/secrets").mock(side_effect=httpx.ConnectError("refused"))
    result = runner.invoke(app, ["secret", "list"])
    assert result.exit_code == 1
    assert "unreachable" in result.output
