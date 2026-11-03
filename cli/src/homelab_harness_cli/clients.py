"""``hh clients list|revoke``: see and cut off the clients that can reach the harness."""

from __future__ import annotations

from typing import Annotated, Any, cast

import typer

from homelab_harness_cli.owner_api import call

clients_app = typer.Typer(
    name="clients", help="OAuth clients and client tokens.", no_args_is_help=True
)

UrlOption = Annotated[
    str | None, typer.Option("--url", help="Harness base URL (default: $HH_CLI_URL).")
]


@clients_app.command("list")
def list_clients(url: UrlOption = None) -> None:
    """List OAuth clients (with live grants) and legacy client tokens."""
    body = call("GET", "/api/clients", url=url)
    rows = cast(list[dict[str, Any]], body.get("clients", []))
    if not rows:
        typer.echo("no clients")
        return
    for row in rows:
        state = f"active ({row['active']})" if row["active"] else "revoked"
        name = f"  {row['name']}" if row["name"] != row["id"] else ""
        typer.echo(f"{row['id']}\t{row['kind']}\t{state}\t{row['created_at']}{name}")


@clients_app.command("revoke")
def revoke(
    client_id: Annotated[str, typer.Argument(help="The id shown by 'hh clients list'.")],
    url: UrlOption = None,
) -> None:
    """Revoke an OAuth client's grants (its tokens stop working at once) or a client token."""
    body = call("POST", f"/api/clients/{client_id}/revoke", url=url)
    typer.echo(f"revoked {body['id']} ({body['revoked']})")
