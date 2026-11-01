"""The capability descriptor core discovers, and the target configuration it reads.

A capability package exposes one :class:`Capability` through the
``homelab_harness.capabilities`` entry-point group. Core loads it without
importing the package by name, reads target entries for it from the targets
file, resolves their credentials, and serves its tools over MCP.
"""

from __future__ import annotations

import tomllib
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from homelab_harness_sdk.tools import ReadTool

ENTRY_POINT_GROUP = "homelab_harness.capabilities"
"""Entry-point group under which capability packages register their :class:`Capability`."""

TARGET_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,62}$"


class CredentialFile(BaseModel):
    """Where a target's credential for one tier lives (interim, until the vault lands).

    Attributes:
        token_id: The credential's public identifier, for example ``harness@pve!read``.
        token_secret_file: File holding only the secret. Core reads it once at
            startup and refuses it if group or others can read it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    token_id: str = Field(min_length=1, max_length=200)
    token_secret_file: Path


class TargetConfig(BaseModel):
    """One target entry in the targets file. Capabilities subclass it with their fields.

    Attributes:
        name: The owner's label for the target, unique within the capability.
        credentials: Credential per tier, keyed by the tier names in the manifest.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=TARGET_NAME_PATTERN)
    credentials: dict[str, CredentialFile] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class Credential:
    """A resolved credential, handed only to a capability's ``connect`` function.

    Attributes:
        tier: Credential tier, for example ``read``.
        token_id: Public identifier; safe to log.
        secret: The secret value. Excluded from ``repr``.
    """

    tier: str
    token_id: str
    secret: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class Manifest:
    """The parsed ``manifest.toml`` of a capability.

    Attributes:
        name: Capability name; every tool name starts with it.
        version: Capability version.
        description: One line for humans.
        credential_tiers: Tier names declared under ``[credentials.*]``.
        tools: Tool name to credential tier, from the ``[tools]`` table.
    """

    name: str
    version: str
    description: str
    credential_tiers: frozenset[str]
    tools: Mapping[str, str]

    @classmethod
    def parse(cls, text: str) -> Manifest:
        """Parse manifest TOML.

        Args:
            text: The file content.

        Returns:
            The manifest.

        Raises:
            ValueError: If required keys are missing or have the wrong type.
        """
        data = tomllib.loads(text)
        try:
            name, version, description = data["name"], data["version"], data["description"]
            credentials = cast(dict[str, Any], data.get("credentials", {}))
            tools = cast(dict[str, Any], data.get("tools", {}))
            tool_tiers = {tool: str(spec["credential"]) for tool, spec in tools.items()}
        except (KeyError, TypeError) as exc:
            raise ValueError(
                "manifest is missing name, version, description or tool tiers"
            ) from exc
        if not all(isinstance(v, str) for v in (name, version, description)):
            raise ValueError("manifest name, version and description must be strings")
        return cls(
            name=name,
            version=version,
            description=description,
            credential_tiers=frozenset(credentials),
            tools=tool_tiers,
        )

    @classmethod
    def load(cls, package: str) -> Manifest:
        """Read ``manifest.toml`` shipped inside ``package``.

        Args:
            package: Import name of the capability package.

        Returns:
            The manifest.
        """
        text = resources.files(package).joinpath("manifest.toml").read_text(encoding="utf-8")
        return cls.parse(text)


type Connector[T: TargetConfig, A] = Callable[[T, Credential], AbstractAsyncContextManager[A]]
type Probe[A] = Callable[[A], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Capability[T: TargetConfig, A]:
    """Everything core needs to serve one capability.

    Attributes:
        manifest: The parsed manifest.
        target_model: Model of one target entry in the targets file.
        connect: Opens an adapter for a target with one credential. It may do
            I/O on enter (for example a TLS probe) and must close on exit.
        probe: A cheap read that proves a target is reachable, for readiness.
        tools: The tools this capability offers.
        probe_credential: Tier the readiness probe uses.

    Raises:
        ValueError: On construction, if a tool name lacks the capability prefix,
            is duplicated, or uses a credential tier the manifest does not declare.
    """

    manifest: Manifest
    target_model: type[T]
    connect: Connector[T, A]
    probe: Probe[A]
    tools: tuple[ReadTool[A, Any, Any], ...]
    probe_credential: str = "read"

    def __post_init__(self) -> None:
        """Check the tool list against the manifest so a bad package fails at load."""
        names = [tool.name for tool in self.tools]
        if len(set(names)) != len(names):
            raise ValueError(f"capability {self.name!r} declares a tool name twice")
        for tool in self.tools:
            if not tool.name.startswith(f"{self.name}."):
                raise ValueError(f"tool {tool.name!r} must start with '{self.name}.'")
            if tool.credential not in self.manifest.credential_tiers:
                raise ValueError(f"tool {tool.name!r} uses undeclared tier {tool.credential!r}")
        if self.probe_credential not in self.manifest.credential_tiers:
            raise ValueError(f"probe tier {self.probe_credential!r} is not in the manifest")

    @property
    def name(self) -> str:
        """The capability name from the manifest."""
        return self.manifest.name
