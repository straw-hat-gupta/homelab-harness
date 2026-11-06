"""Reads behind the UI façade: capability read tools, called the way MCP calls them.

**Interim** until the Stage 2 lab state backs the UI. Tools are found by name
among the capabilities core discovered through their entry point, and run with
the same :class:`~homelab_harness.mcp.context.CoreToolContext` the MCP server
uses, so the UI gets exactly what an agent would: the ``read`` credential tier,
masked guest config, owner-safe errors. Core never imports a capability package.

Every façade request writes one ``ui.read`` audit event (S10) naming the view,
the tools and the targets, never the results. As with MCP, a request whose audit
write fails returns no data.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

import structlog
from pydantic import ValidationError

from homelab_harness.audit.service import AuditWriter
from homelab_harness.capabilities import AnyCapability
from homelab_harness.mcp.context import CoreToolContext
from homelab_harness.redaction import Redactor, redactor
from homelab_harness.targets import TargetRegistry
from homelab_harness.ui import views
from homelab_harness.ui.views import ObjectRef, ObjectSummary, ObjectType, TreeResponse
from homelab_harness_sdk import HarnessError, InvalidInput, ReadTool

log = structlog.get_logger(__name__)

AUDIT_KIND = "ui.read"
PROXMOX = "proxmox"

type Tool = ReadTool[Any, Any, Any]


class UiUnavailable(Exception):
    """The façade cannot answer: no capability, or its audit write failed."""


class _Call:
    """Tool calls of one façade request, for its audit event."""

    def __init__(self) -> None:
        self.tools: list[str] = []
        self.targets: list[str] = []
        self.error_type: str | None = None


class UiReadService:
    """The UI's interim read model over capability read tools."""

    def __init__(
        self,
        *,
        capabilities: Mapping[str, AnyCapability],
        registry: Callable[[], TargetRegistry],
        audit: Callable[[], AuditWriter | None],
        scrubber: Redactor = redactor,
    ) -> None:
        """Index the installed tools.

        Args:
            capabilities: Installed capabilities by name.
            registry: Returns the current target registry (it is filled at startup).
            audit: Returns the audit writer, or ``None`` without a database.
            scrubber: Redactor applied to every tool result.
        """
        self._capabilities = capabilities
        self._tools: dict[str, tuple[AnyCapability, Tool]] = {
            tool.name: (cap, tool) for cap in capabilities.values() for tool in cap.tools
        }
        self._registry = registry
        self._audit = audit
        self._scrubber = scrubber

    async def tree(self, *, client_id: str) -> TreeResponse:
        """Every registered Proxmox cluster with its nodes, guests and storages.

        An unreachable cluster is listed with its owner-safe error instead of
        failing the whole tree.

        Args:
            client_id: The owner client, for the audit event.

        Returns:
            The tree.

        Raises:
            UiUnavailable: If the audit write fails.
        """
        call = _Call()
        started = time.monotonic()
        clusters: list[views.TreeCluster] = []
        for name in self._registry().names(PROXMOX):
            try:
                result = await self._run(call, "proxmox.cluster.resources", {"cluster": name})
            except HarnessError as exc:
                clusters.append(views.unreachable_cluster(name, exc.safe_message))
                continue
            clusters.append(views.tree_cluster(name, result))
        await self._record(call, client_id=client_id, view="tree", started=started)
        return TreeResponse(clusters=clusters)

    async def summary(
        self, *, client_id: str, object_type: ObjectType, object_id: str
    ) -> ObjectSummary:
        """The Summary tab's data for one object.

        Args:
            client_id: The owner client, for the audit event.
            object_type: The object type.
            object_id: The object id (see :mod:`homelab_harness.ui.views`).

        Returns:
            The summary.

        Raises:
            InvalidInput: If the id is malformed or names an unknown cluster.
            HarnessError: The tool's own error (``NotFound``, ``TargetUnavailable`` …).
            UiUnavailable: If the capability is missing or the audit write fails.
        """
        ref = views.parse_object_id(object_type, object_id)
        call = _Call()
        started = time.monotonic()
        try:
            summary = await self._summary(call, ref)
        except HarnessError as exc:
            call.error_type = type(exc).__name__
            await self._record(call, client_id=client_id, view="summary", started=started)
            raise
        await self._record(call, client_id=client_id, view="summary", started=started)
        return summary

    async def _summary(self, call: _Call, ref: ObjectRef) -> ObjectSummary:
        # Reject an unknown cluster before any tool runs, with the registry's message.
        self._registry().get(PROXMOX, ref.cluster)
        match ref.type:
            case "datacenter":
                result = await self._run(call, "proxmox.cluster.list", {"cluster": ref.cluster})
                return views.datacenter_summary(ref, result)
            case "node":
                args = {"cluster": ref.cluster, "node": ref.node}
                return views.node_summary(ref, await self._run(call, "proxmox.node.get", args))
            case "qemu" | "lxc":
                args = {"cluster": ref.cluster, "vmid": ref.vmid, "type": ref.type}
                return views.guest_summary(ref, await self._run(call, "proxmox.guest.get", args))
            case "storage":
                args = {"cluster": ref.cluster, "node": ref.node, "storage": ref.storage}
                result = await self._run(call, "proxmox.storage.status", args)
                return views.storage_summary(ref, result)

    async def _run(self, call: _Call, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        entry = self._tools.get(name)
        if entry is None:
            raise UiUnavailable(f"the {name.split('.')[0]} capability is not installed")
        capability, tool = entry
        context = CoreToolContext(
            capability=capability, registry=self._registry(), credential_tier=tool.credential
        )
        try:
            args = tool.input_model.model_validate(arguments)
        except ValidationError:
            raise InvalidInput("the object id is out of range") from None
        call.tools.append(name)
        try:
            output = await tool(context, args)
        finally:
            call.targets.extend(t for t in context.used_targets if t not in call.targets)
        data: dict[str, Any] = self._scrubber.scrub_values(output.model_dump(mode="json"))
        return data

    async def _record(self, call: _Call, *, client_id: str, view: str, started: float) -> None:
        duration_ms = round((time.monotonic() - started) * 1000)
        data: dict[str, object] = {
            "view": view,
            "tools": call.tools,
            "targets": call.targets,
            "outcome": "ok" if call.error_type is None else "error",
            "duration_ms": duration_ms,
        }
        if call.error_type is not None:
            data["error_type"] = call.error_type
        writer = self._audit()
        try:
            if writer is None:
                raise RuntimeError("audit log is not configured")
            await writer.record(
                kind=AUDIT_KIND,
                actor=f"client:{client_id}",
                target=call.targets[0] if len(call.targets) == 1 else None,
                data=data,
            )
        except Exception as exc:  # fail closed, as MCP does: no unaudited reads
            log.error("ui_audit_failed", view=view, error_type=type(exc).__name__)
            raise UiUnavailable("the harness could not record this read in its audit log") from exc
        log.info("ui_read", view=view, client_id=client_id, tools=len(call.tools))
