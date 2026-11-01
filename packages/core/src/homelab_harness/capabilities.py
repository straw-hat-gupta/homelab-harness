"""Discovery of installed capabilities through Python entry points.

Core depends on no capability package. Each one registers a
:class:`~homelab_harness_sdk.Capability` under the ``homelab_harness.capabilities``
group in its ``pyproject.toml``; installing the package is what enables it.
"""

from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points
from typing import Any

import structlog

from homelab_harness_sdk import ENTRY_POINT_GROUP, Capability

log = structlog.get_logger(__name__)

type AnyCapability = Capability[Any, Any]


def discover_capabilities(
    found: tuple[EntryPoint, ...] | None = None,
) -> dict[str, AnyCapability]:
    """Load every capability registered in the entry-point group.

    Args:
        found: Entry points to load instead of the installed ones (tests).

    Returns:
        Capabilities by name, in name order.

    Raises:
        TypeError: If an entry point does not resolve to a ``Capability``.
        ValueError: If two packages register the same capability name.
    """
    points = found if found is not None else tuple(entry_points(group=ENTRY_POINT_GROUP))
    loaded: dict[str, AnyCapability] = {}
    for point in sorted(points, key=lambda p: p.name):
        capability: object = point.load()
        if not isinstance(capability, Capability):
            raise TypeError(f"entry point {point.name!r} is not a homelab_harness_sdk.Capability")
        typed: AnyCapability = capability  # pyright: ignore[reportUnknownVariableType]
        if typed.name in loaded:
            raise ValueError(f"capability {typed.name!r} is registered twice")
        loaded[typed.name] = typed
        log.info("capability_loaded", capability=typed.name, tools=len(typed.tools))
    return loaded
