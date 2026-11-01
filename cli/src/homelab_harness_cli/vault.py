"""``hh secret ...`` and ``hh vault ...``: the owner's vault commands.

Values are read from a hidden prompt (the default), ``--stdin`` or
``--from-file``, never from the command line, where shell history and ``ps``
would keep them. Nothing here prints a value: the harness never returns one.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from homelab_harness_cli.owner_api import call, fail

secret_app = typer.Typer(
    name="secret", help="Store and manage vault secrets.", no_args_is_help=True
)
vault_app = typer.Typer(name="vault", help="Vault maintenance.", no_args_is_help=True)

_ARGV_REFUSAL = (
    "values are never taken from the command line (shell history and ps keep them); "
    "use the hidden prompt, --stdin or --from-file"
)
# Rewrapping touches every stored version, so it may take longer than one request.
_REWRAP_TIMEOUT_SECONDS = 300.0

UrlOption = Annotated[
    str | None, typer.Option("--url", help="Harness base URL (default: $HH_CLI_URL).")
]
FromFile = Annotated[
    Path | None,
    typer.Option("--from-file", help="Read the value from this file.", dir_okay=False),
]
Stdin = Annotated[bool, typer.Option("--stdin", help="Read the value from standard input.")]
Keys = Annotated[
    list[str] | None,
    typer.Option("--key", help="kv: a key to prompt for (repeatable)."),
]
Meta = Annotated[
    list[str] | None,
    typer.Option("--meta", help="Plain metadata KEY=VALUE (repeatable), e.g. token_id=..."),
]
MetaJson = Annotated[
    str | None, typer.Option("--meta-json", help="Plain metadata as a JSON object.")
]
# Declared only so a value passed this way is refused instead of parsed.
Value = Annotated[str | None, typer.Option("--value", hidden=True)]

_ACCEPT_EXTRA = {"allow_extra_args": True, "ignore_unknown_options": True}


def _refuse_argv_values(ctx: typer.Context, value: str | None) -> None:
    # Extra arguments may be a value typed after the name; refuse without echoing them.
    if value is not None or ctx.args:
        raise fail(_ARGV_REFUSAL)


def _metadata(meta: list[str] | None, meta_json: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if meta_json is not None:
        try:
            parsed: object = json.loads(meta_json)
        except ValueError:
            raise fail("--meta-json is not valid JSON") from None
        if not isinstance(parsed, dict):
            raise fail("--meta-json must be a JSON object")
        out.update(parsed)  # pyright: ignore[reportUnknownArgumentType]
    for item in meta or []:
        key, sep, val = item.partition("=")
        if not sep or not key:
            raise fail("--meta takes KEY=VALUE")
        out[key] = val
    return out


def _read_bytes(from_file: Path | None, stdin: bool) -> bytes | None:
    if from_file is not None and stdin:
        raise fail("use one of --from-file and --stdin")
    if from_file is not None:
        try:
            return from_file.expanduser().read_bytes()
        except OSError:
            raise fail(f"cannot read {from_file}") from None
    if stdin:
        return sys.stdin.buffer.read()
    return None


def _text(data: bytes) -> str:
    try:
        return data.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError:
        raise fail("the value is not UTF-8 text") from None


def _kv_lines(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, val = line.partition("=")
        if not sep or not key.strip():
            raise fail(f"kv input line {number} is not KEY=VALUE")
        values[key.strip()] = val
    return values


def _prompt(label: str) -> str:
    value: str = typer.prompt(label, hide_input=True, confirmation_prompt=True)
    if not value:
        raise fail("empty value")
    return value


def _value_body(
    *,
    name: str,
    kind: str,
    from_file: Path | None,
    stdin: bool,
    keys: list[str] | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Build the ``value`` or ``fields`` part of a create or rotate request."""
    data = _read_bytes(from_file, stdin)
    if kind == "file":
        if data is None:
            raise fail("file secrets need --from-file or --stdin")
        if from_file is not None:
            metadata.setdefault("filename", from_file.name)
        return {"fields": {"content": base64.b64encode(data).decode()}}
    if kind == "kv":
        if data is not None:
            return {"fields": {"values": _kv_lines(_text(data))}}
        if not keys:
            raise fail("kv secrets need --key NAME (prompted) or KEY=VALUE lines on --stdin")
        return {"fields": {"values": {k: _prompt(f"Value for {name}.{k}") for k in keys}}}
    if data is not None:
        return {"value": _text(data)}
    if kind == "ssh_key":
        raise fail("ssh_key secrets need --from-file or --stdin (or use 'hh secret generate')")
    return {"value": _prompt(f"Value for {name}")}


def _print_secret(secret: dict[str, Any]) -> None:
    status = "revoked" if secret.get("revoked_at") else "active"
    typer.echo(f"{secret['handle']}  ({secret['kind']}, v{secret['current_version']}, {status})")
    for label, key in (
        ("description", "description"),
        ("created", "created_at"),
        ("rotated", "rotated_at"),
        ("expires", "expires_at"),
        ("revoked", "revoked_at"),
    ):
        if secret.get(key):
            typer.echo(f"  {label + ':':<16}{secret[key]}")
    if secret.get("rotate_every_seconds"):
        typer.echo(f"  {'rotate every:':<16}{secret['rotate_every_seconds'] // 86400} day(s)")
    if secret.get("tags"):
        typer.echo(f"  {'tags:':<16}{', '.join(secret['tags'])}")
    for key, val in sorted(secret.get("metadata", {}).items()):
        if val not in (None, "", []):
            typer.echo(f"  {key + ':':<16}{val}")
    for version in secret.get("versions", []):
        when, kek = version["created_at"], version["kek_id"]
        typer.echo(f"  version {version['version']}: {when} (KEK {kek})")


@secret_app.command("add", context_settings=_ACCEPT_EXTRA)
def add(
    ctx: typer.Context,
    name: str,
    kind: Annotated[str, typer.Option("--kind", help="ssh_key, password, api_token, ...")],
    from_file: FromFile = None,
    stdin: Stdin = False,
    key: Keys = None,
    description: Annotated[str, typer.Option("--description")] = "",
    tag: Annotated[list[str] | None, typer.Option("--tag", help="Repeatable.")] = None,
    meta: Meta = None,
    meta_json: MetaJson = None,
    expires_at: Annotated[
        str | None, typer.Option("--expires-at", help="ISO 8601 with a time zone.")
    ] = None,
    rotate_every_days: Annotated[int | None, typer.Option("--rotate-every-days", min=1)] = None,
    value: Value = None,
    url: UrlOption = None,
) -> None:
    """Store a new secret. The value is prompted for, hidden, unless read from a file or stdin."""
    _refuse_argv_values(ctx, value)
    metadata = _metadata(meta, meta_json)
    body: dict[str, Any] = {
        "name": name,
        "kind": kind,
        **_value_body(
            name=name, kind=kind, from_file=from_file, stdin=stdin, keys=key, metadata=metadata
        ),
        "metadata": metadata,
        "description": description,
        "tags": tag or [],
        "expires_at": expires_at,
        "rotate_every_seconds": rotate_every_days * 86400 if rotate_every_days else None,
    }
    secret = call("POST", "/api/secrets", url=url, json=body)
    typer.echo(f"stored {secret['handle']} (version {secret['current_version']})")


@secret_app.command("list")
def list_secrets(url: UrlOption = None) -> None:
    """List secrets (names, kinds, versions; never values)."""
    secrets = call("GET", "/api/secrets", url=url)["secrets"]
    if not secrets:
        typer.echo("no secrets")
    for secret in secrets:
        status = "revoked" if secret.get("revoked_at") else "active"
        expires = f"  expires {secret['expires_at']}" if secret.get("expires_at") else ""
        typer.echo(
            f"{secret['name']:<32} {secret['kind']:<17} v{secret['current_version']:<4}"
            f"{status}{expires}"
        )


@secret_app.command("show")
def show(name: str, url: UrlOption = None) -> None:
    """Show one secret's metadata and versions (never its value)."""
    _print_secret(call("GET", f"/api/secrets/{name}", url=url))


@secret_app.command("rotate", context_settings=_ACCEPT_EXTRA)
def rotate(
    ctx: typer.Context,
    name: str,
    from_file: FromFile = None,
    stdin: Stdin = False,
    key: Keys = None,
    meta: Meta = None,
    meta_json: MetaJson = None,
    generate: Annotated[
        bool, typer.Option("--generate", help="ssh_key: generate a new key in the harness.")
    ] = False,
    value: Value = None,
    url: UrlOption = None,
) -> None:
    """Store a new version of a secret; older versions are kept."""
    _refuse_argv_values(ctx, value)
    metadata = _metadata(meta, meta_json) if (meta or meta_json) else None
    if generate:
        body: dict[str, Any] = {"generate": True, "metadata": metadata}
    else:
        kind = call("GET", f"/api/secrets/{name}", url=url)["kind"]
        # Without --meta the harness keeps the stored metadata (a file keeps its name).
        value_part = _value_body(
            name=name, kind=kind, from_file=from_file, stdin=stdin, keys=key, metadata={}
        )
        body = {**value_part, "metadata": metadata}
    secret = call("POST", f"/api/secrets/{name}/versions", url=url, json=body)
    typer.echo(f"rotated {secret['handle']} to version {secret['current_version']}")
    if secret["kind"] == "ssh_key":
        typer.echo(secret["metadata"]["public_key"])


@secret_app.command("revoke")
def revoke(name: str, url: UrlOption = None) -> None:
    """Make a secret unusable until it is rotated."""
    call("POST", f"/api/secrets/{name}/revoke", url=url)
    typer.echo(f"revoked secret://{name}")


@secret_app.command("delete")
def delete(
    name: str,
    confirm: Annotated[
        str | None, typer.Option("--confirm", help="The secret's name, to skip the prompt.")
    ] = None,
    url: UrlOption = None,
) -> None:
    """Crypto-shred a secret: every version is destroyed and cannot be recovered."""
    typed = confirm
    if typed is None:
        typer.echo(f"This destroys every version of secret://{name}. It cannot be undone.")
        typed = typer.prompt("Type the secret's name to confirm")
    if typed != name:
        raise fail("the name did not match; nothing was deleted")
    result = call("DELETE", f"/api/secrets/{name}", url=url, params={"confirm": typed})
    typer.echo(f"deleted secret://{name} ({result['versions_destroyed']} version(s) destroyed)")


@secret_app.command("generate")
def generate(
    kind: Annotated[str, typer.Argument(help="Only ssh_key for now.")],
    name: str,
    comment: Annotated[str, typer.Option("--comment")] = "",
    from_host: Annotated[
        list[str] | None,
        typer.Option("--from", help="authorized_keys from= pattern (repeatable)."),
    ] = None,
    description: Annotated[str, typer.Option("--description")] = "",
    tag: Annotated[list[str] | None, typer.Option("--tag", help="Repeatable.")] = None,
    url: UrlOption = None,
) -> None:
    """Generate a key inside the harness; print only its public key."""
    if kind != "ssh_key":
        raise fail("only ssh_key can be generated for now")
    body = {
        "name": name,
        "kind": kind,
        "comment": comment,
        "from_hosts": from_host or [],
        "description": description,
        "tags": tag or [],
    }
    result = call("POST", "/api/secrets/generate", url=url, json=body)
    typer.echo(f"stored {result['secret']['handle']}; the private key never leaves the harness")
    typer.echo(f"fingerprint: {result['secret']['metadata']['fingerprint']}")
    typer.echo("authorized_keys line:")
    typer.echo(result["authorized_keys"])


@vault_app.command("rotate-kek")
def rotate_kek(url: UrlOption = None) -> None:
    """Rewrap every data key under the harness's current KEK (values are not re-encrypted).

    Put the new KEK first in the keyring and restart the harness before running
    this; remove the old KEK only after it reports 0 failed.
    """
    report = call("POST", "/api/vault/rotate-kek", url=url, timeout_seconds=_REWRAP_TIMEOUT_SECONDS)
    typer.echo(
        f"current KEK {report['kek_id']}: {report['rewrapped']} rewrapped, "
        f"{report['already_current']} already current, {report['failed']} failed"
    )
    if report["failed"]:
        raise typer.Exit(1)
