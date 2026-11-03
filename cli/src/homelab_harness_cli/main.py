"""``hh`` entry point.

Every command talks to the harness over HTTP; the CLI never touches the database
or targets directly, so it uses exactly the same policy path as any other client.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Annotated

import httpx
import typer

from homelab_harness_cli.clients import clients_app
from homelab_harness_cli.owner_api import CliSettings
from homelab_harness_cli.vault import secret_app, vault_app

app = typer.Typer(
    name="hh",
    help="Homelab Harness: the owner's CLI.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(secret_app)
app.add_typer(vault_app)
app.add_typer(clients_app)


def _cli_version() -> str:
    try:
        return version("homelab-harness-cli")
    except PackageNotFoundError:  # pragma: no cover
        return "0.0.0+unknown"


UrlOption = Annotated[
    str | None, typer.Option("--url", help="Harness base URL (default: $HH_CLI_URL).")
]


@app.command("version")
def show_version() -> None:
    """Print the CLI version."""
    typer.echo(f"hh {_cli_version()}")


@app.command()
def health(url: UrlOption = None) -> None:
    """Check that the harness is up and ready.

    Exits 0 when ready (ok or degraded), 1 when it is unreachable or failing.
    """
    settings = CliSettings()
    base = (url or settings.url).rstrip("/")
    try:
        with httpx.Client(base_url=base, timeout=settings.timeout_seconds) as client:
            live = client.get("/healthz")
            ready = client.get("/readyz")
    except httpx.HTTPError as exc:
        typer.echo(f"unreachable: {base} ({type(exc).__name__})", err=True)
        raise typer.Exit(1) from exc

    if live.status_code != 200:
        typer.echo(f"not live: HTTP {live.status_code}", err=True)
        raise typer.Exit(1)
    report = ready.json()
    typer.echo(f"harness {live.json().get('version', '?')} at {base}: {report['status']}")
    for name, check in sorted(report.get("checks", {}).items()):
        detail = f" ({check['detail']})" if check.get("detail") else ""
        typer.echo(f"  {check['status']:<9} {name}{detail}")
    if ready.status_code != 200:
        raise typer.Exit(1)
