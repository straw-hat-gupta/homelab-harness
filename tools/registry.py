from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolDef:
    name: str
    description: str
    # JSON Schema–style properties dict describing the tool's params (excluding token_data /
    # user_id, which are injected automatically by the orchestrator).
    # Used to build the planner's system prompt.
    params_schema: Dict[str, Any]
    fn: Callable                        # async callable
    display_name: Optional[str] = None  # human-readable label for the frontend (e.g. "Archive Message")
    requires_creds: bool = False
    plugin_id: Optional[str] = None     # used for credential lookup when requires_creds=True
    requires_confirmation: bool = False  # True for irreversible external side effects
    requires_user_id: bool = False       # True if the tool needs user_id injected as a kwarg


_REGISTRY: Dict[str, ToolDef] = {}


class UnknownToolError(Exception):
    """Raised when a plan references a tool name not present in the registry."""


def register(tool_def: ToolDef) -> None:
    _REGISTRY[tool_def.name] = tool_def


def get(name: str) -> ToolDef:
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise UnknownToolError(
            f"Tool {name!r} is not registered. Available tools: {available}"
        )
    return _REGISTRY[name]


def get_schemas_for_planner(enabled_plugins: Optional[frozenset] = None) -> List[Dict[str, Any]]:
    result = []
    for t in _REGISTRY.values():
        if enabled_plugins is not None and t.plugin_id is not None and t.plugin_id not in enabled_plugins:
            continue
        result.append({
            "name": t.name,
            "display_name": t.display_name or t.name,
            "description": t.description,
            "plugin_id": t.plugin_id,
            "params": t.params_schema,
        })
    return result
