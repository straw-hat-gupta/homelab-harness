"""The Proxmox capability descriptor, discovered by core through its entry point.

``pyproject.toml`` registers :data:`CAPABILITY` under the
``homelab_harness.capabilities`` group. Core never imports this package by name.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from pydantic import Field, field_validator

from homelab_harness_proxmox.adapter import ApiToken, Endpoint, ProxmoxClient
from homelab_harness_proxmox.tls import TlsTrust
from homelab_harness_proxmox.tools import TOOLS
from homelab_harness_sdk import Capability, Credential, InvalidInput, Manifest, TargetConfig


class ProxmoxTarget(TargetConfig):
    """One Proxmox VE cluster (a standalone node is a one-node cluster).

    Attributes:
        endpoints: API addresses, ``host`` or ``host:port`` (``[v6]:port`` for
            IPv6). Reads use the first one; node routing (§3) is not built yet.
        tls: How to verify the nodes' certificates. There is no insecure option.
    """

    endpoints: list[str] = Field(min_length=1, max_length=32)
    tls: TlsTrust

    @field_validator("endpoints")
    @classmethod
    def _parse(cls, value: list[str]) -> list[str]:
        for item in value:
            parse_endpoint(item)
        return value


def parse_endpoint(value: str) -> Endpoint:
    """Parse ``host``, ``host:port`` or ``[v6]:port`` into an :class:`Endpoint`.

    Args:
        value: The configured address.

    Returns:
        The endpoint.

    Raises:
        InvalidInput: If the address is malformed (the value is not echoed).
    """
    host, port = value, None
    if value.startswith("["):
        host, sep, rest = value[1:].partition("]")
        if not sep or (rest and not rest.startswith(":")):
            raise InvalidInput("invalid Proxmox endpoint")
        port = rest[1:] or None
    elif value.count(":") == 1:
        host, port = value.split(":")
    if port is not None and not port.isdigit():
        raise InvalidInput("invalid Proxmox endpoint")
    return Endpoint(host=host) if port is None else Endpoint(host=host, port=int(port))


def api_token(credential: Credential) -> ApiToken:
    """Build the PVE token from a resolved credential (``user@realm!tokenid`` + secret).

    Args:
        credential: The credential core resolved for one tier.

    Returns:
        The token.

    Raises:
        InvalidInput: If the token ID is not ``user@realm!tokenid``.
    """
    user, sep, token_id = credential.token_id.partition("!")
    if not sep:
        raise InvalidInput("Proxmox token_id must look like 'user@realm!tokenid'")
    return ApiToken(user=user, token_id=token_id, secret=credential.secret)


@asynccontextmanager
async def connect(target: ProxmoxTarget, credential: Credential) -> AsyncGenerator[ProxmoxClient]:
    """Open a read-only client for the cluster's first endpoint.

    Args:
        target: The cluster's configuration.
        credential: The credential for the tier the caller needs.

    Yields:
        An entered :class:`ProxmoxClient`.
    """
    client = ProxmoxClient(
        endpoint=parse_endpoint(target.endpoints[0]), token=api_token(credential), trust=target.tls
    )
    async with client:
        yield client


async def probe(client: ProxmoxClient) -> None:
    """Readiness probe: ``GET /version``, the cheapest authenticated read."""
    await client.version()


CAPABILITY: Capability[ProxmoxTarget, ProxmoxClient] = Capability(
    manifest=Manifest.load("homelab_harness_proxmox"),
    target_model=ProxmoxTarget,
    connect=connect,
    probe=probe,
    tools=TOOLS,
)
"""The descriptor registered under the ``homelab_harness.capabilities`` entry point."""
