"""HTTP calls to the harness's owner API (``/api``), with the owner token.

The token comes from ``HH_CLI_TOKEN_FILE`` (preferred: a file only you can read)
or ``HH_CLI_TOKEN``. Create it on the harness host with
``homelab-harness-token create --client hh --role owner``.
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any, cast

import httpx
import typer
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_SETUP_HINT = (
    "set HH_CLI_TOKEN_FILE (or HH_CLI_TOKEN) to an owner token from "
    "'homelab-harness-token create --client hh --role owner'"
)


class CliSettings(BaseSettings):
    """CLI configuration from ``HH_CLI_*`` environment variables.

    Attributes:
        url: Base URL of the harness (usually a tailnet address).
        timeout_seconds: HTTP timeout for each request.
        token: Owner token. Prefer ``token_file``: environment variables are
            inherited by every child process.
        token_file: File holding only the owner token; it must not be readable
            by group or others.
    """

    model_config = SettingsConfigDict(env_prefix="HH_CLI_", env_file=None, extra="ignore")

    url: str = "http://127.0.0.1:8080"
    timeout_seconds: float = 5.0
    token: SecretStr | None = None
    token_file: Path | None = None


def fail(message: str) -> typer.Exit:
    """Print ``message`` to stderr and return the exit to raise."""
    typer.echo(message, err=True)
    return typer.Exit(1)


def _read_token_file(path: Path) -> str:
    try:
        info = path.stat()
        if info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode):
            raise fail(f"{path} must be a regular file readable only by you (chmod 0600)")
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        raise fail(f"cannot read the token file {path}") from None
    if not token:
        raise fail(f"the token file {path} is empty")
    return token


def _owner_token(settings: CliSettings) -> str:
    if settings.token_file is not None:
        return _read_token_file(settings.token_file.expanduser())
    if settings.token is not None and settings.token.get_secret_value().strip():
        return settings.token.get_secret_value().strip()
    raise fail(f"no owner token: {_SETUP_HINT}")


def _detail(response: httpx.Response) -> str:
    try:
        body: object = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    detail: object = cast(dict[str, object], body).get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        # Validation errors: field locations and rules only (the harness strips input).
        parts: list[str] = []
        for item in cast(list[object], detail):
            if isinstance(item, dict):
                err = cast(dict[str, Any], item)
                loc = ".".join(str(p) for p in err.get("loc", []))
                parts.append(f"{loc}: {err.get('msg', '')}")
        return "; ".join(parts) or f"HTTP {response.status_code}"
    return f"HTTP {response.status_code}"


def call(
    method: str,
    path: str,
    *,
    url: str | None = None,
    json: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Make one owner API call and return the JSON body, or exit 1 with a message.

    Args:
        method: HTTP method.
        path: Path under the base URL, for example ``/api/secrets``.
        url: Base URL override (``--url``).
        json: Request body.
        params: Query parameters.
        timeout_seconds: Override of the configured timeout, for slow calls.

    Returns:
        The decoded JSON object.

    Raises:
        typer.Exit: On a network error or a non-2xx answer; the message is the
            harness's owner-safe ``detail``.
    """
    settings = CliSettings()
    base = (url or settings.url).rstrip("/")
    headers = {"Authorization": f"Bearer {_owner_token(settings)}"}
    try:
        with httpx.Client(
            base_url=base, timeout=timeout_seconds or settings.timeout_seconds, headers=headers
        ) as client:
            response = client.request(method, path, json=json, params=params)
    except httpx.HTTPError as exc:
        raise fail(f"unreachable: {base} ({type(exc).__name__})") from None
    if response.status_code == 401:
        raise fail(f"the harness refused the owner token: {_SETUP_HINT}")
    if response.is_error:
        raise fail(f"error: {_detail(response)}")
    body: object = response.json()
    if not isinstance(body, dict):
        raise fail("error: unexpected response from the harness")
    return body  # pyright: ignore[reportUnknownVariableType]
