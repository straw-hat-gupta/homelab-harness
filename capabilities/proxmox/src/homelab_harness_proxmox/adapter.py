"""Typed, async, read-only client for one Proxmox VE API endpoint (§3).

No policy, no database, no writes: every method is a ``GET``. Each failure is
mapped to ``homelab_harness_sdk.errors``. Write methods arrive with the
executors, behind jobs (S1).

Usage::

    async with ProxmoxClient(endpoint=ep, token=tok, trust=CaBundle(path=ca)) as pve:
        nodes = await pve.list_nodes()
"""

from __future__ import annotations

import re
import ssl
import time
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self, cast
from urllib.parse import quote

import httpx
import structlog
from pydantic import ValidationError

from homelab_harness_proxmox import identifiers
from homelab_harness_proxmox.errors import (
    TlsVerificationFailed,
    UnexpectedResponse,
    map_status_error,
)
from homelab_harness_proxmox.models import (
    BackupJob,
    ClusterStatusEntry,
    Disk,
    Guest,
    GuestConfig,
    GuestStatus,
    GuestType,
    HaStatusEntry,
    Listing,
    NetworkConfig,
    NetworkInterface,
    NodeStatus,
    NodeSummary,
    Pool,
    Resource,
    ResourceType,
    RrdConsolidation,
    RrdPoint,
    RrdTimeframe,
    SmartData,
    StorageConfig,
    StorageStatus,
    StorageVolume,
    Task,
    TaskLog,
    TaskLogLine,
    TaskStatus,
    Version,
)
from homelab_harness_proxmox.tls import TlsTrust, build_ssl_context
from homelab_harness_proxmox.upid import Upid, parse_upid
from homelab_harness_sdk.errors import (
    HarnessError,
    InvalidInput,
    TargetUnavailable,
)

logger = structlog.get_logger(__name__)

DEFAULT_PORT = 8006
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0
# SMART collection runs smartctl per disk and can be slow on large chassis (§3).
SLOW_READ_TIMEOUT = 120.0

_USER = re.compile(r"[^\s:@!]+@[A-Za-z0-9.\-_]+")
_TOKEN_ID = re.compile(r"[A-Za-z][A-Za-z0-9.\-_]+")


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Endpoint:
    """One node's API address.

    Attributes:
        host: Hostname or IP (no scheme, no port).
        port: API port, 8006 unless pveproxy is remapped.
    """

    host: str
    port: int = DEFAULT_PORT

    def __post_init__(self) -> None:
        """Reject anything that is not a bare host, so it cannot alter the URL."""
        if not self.host or any(c in self.host for c in "/?#@ \t\r\n") or self.host.count(":") == 1:
            raise InvalidInput("invalid Proxmox host")
        if not 0 < self.port < 65536:
            raise InvalidInput("invalid Proxmox port")

    @property
    def base_url(self) -> str:
        """``https://host:port/api2/json``, with IPv6 literals bracketed."""
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"https://{host}:{self.port}/api2/json"


@dataclass(frozen=True, slots=True)
class ApiToken:
    """A PVE API token. The secret never appears in ``repr``, ``str`` or errors.

    The secret is a plain ``str`` for now; it will come from the vault as a
    brokered handle once that lands (docs/spec/secrets.md).

    Attributes:
        user: ``user@realm``, for example ``harness@pve``.
        token_id: Token name, for example ``read``.
    """

    user: str
    token_id: str
    secret: str = field(repr=False)

    def __post_init__(self) -> None:
        """Validate the parts without ever echoing them in the message."""
        if _USER.fullmatch(self.user) is None or _TOKEN_ID.fullmatch(self.token_id) is None:
            raise InvalidInput("invalid Proxmox API token identity")
        if not self.secret or any(c.isspace() or not c.isprintable() for c in self.secret):
            raise InvalidInput("invalid Proxmox API token secret")

    @property
    def full_id(self) -> str:
        """``user@realm!tokenid``; safe to log."""
        return f"{self.user}!{self.token_id}"


class _PveTokenAuth(httpx.Auth):
    """Adds ``Authorization: PVEAPIToken=…`` per request, so no client holds the header."""

    def __init__(self, token: ApiToken) -> None:
        self._token = token

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response]:
        request.headers["Authorization"] = f"PVEAPIToken={self._token.full_id}={self._token.secret}"
        yield request

    def __repr__(self) -> str:
        return f"_PveTokenAuth(token={self._token.full_id})"


def _seg(value: str | int) -> str:
    return quote(str(value), safe="")


def _guest_type(value: str) -> GuestType:
    if value not in ("qemu", "lxc"):
        raise InvalidInput("guest type must be qemu or lxc")
    return value


class ProxmoxClient:
    """Read-only Proxmox VE API client for one endpoint.

    Enter it with ``async with`` before use: entering builds the verifying TLS
    context (probing the node when a fingerprint is pinned).
    """

    def __init__(
        self,
        *,
        endpoint: Endpoint,
        token: ApiToken,
        trust: TlsTrust,
        connect_timeout: float = CONNECT_TIMEOUT,
        read_timeout: float = READ_TIMEOUT,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Configure the client; no I/O happens until it is entered.

        Args:
            endpoint: Node address.
            token: API token for the tier this client serves.
            trust: How to verify the node's certificate. There is no insecure option.
            connect_timeout: Seconds to establish TCP and TLS.
            read_timeout: Seconds to wait for a response, for normal reads.
            clock: Source of aware UTC ``as_of`` timestamps (injectable for tests).
        """
        self._endpoint = endpoint
        self._token = token
        self._trust = trust
        self._timeout = httpx.Timeout(
            connect=connect_timeout, read=read_timeout, write=read_timeout, pool=connect_timeout
        )
        self._clock = clock
        self._http: httpx.AsyncClient | None = None

    def __repr__(self) -> str:
        return (
            f"ProxmoxClient(host={self._endpoint.host!r}, port={self._endpoint.port}, "
            f"token={self._token.full_id!r})"
        )

    async def __aenter__(self) -> Self:
        context = await build_ssl_context(
            self._trust,
            host=self._endpoint.host,
            port=self._endpoint.port,
            connect_timeout=self._timeout.connect or CONNECT_TIMEOUT,
        )
        self._http = httpx.AsyncClient(
            base_url=self._endpoint.base_url,
            auth=_PveTokenAuth(self._token),
            verify=context,
            timeout=self._timeout,
            # Proxy variables and SSL_CERT_FILE must not change where the token goes
            # or which certificates are trusted.
            trust_env=False,
            follow_redirects=False,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # -- transport -----------------------------------------------------------------

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        read_timeout: float | None = None,
    ) -> dict[str, Any]:
        """GET ``path`` and return the decoded JSON envelope (``{"data": …}``)."""
        if self._http is None:
            raise RuntimeError("ProxmoxClient must be entered with 'async with' before use")
        target = self._endpoint.host
        timeout = self._timeout if read_timeout is None else self._timeout_with_read(read_timeout)
        started = time.monotonic()
        try:
            response = await self._http.get(path, params=params, timeout=timeout)
        except httpx.TransportError as exc:
            raise self._transport_error(exc, path) from exc
        elapsed_ms = round((time.monotonic() - started) * 1000)
        logger.debug(
            "proxmox.request",
            method="GET",
            path=path,
            status=response.status_code,
            elapsed_ms=elapsed_ms,
            target=target,
        )
        body = self._json_or_none(response)
        if not response.is_success:
            error = map_status_error(
                status=response.status_code,
                reason=response.reason_phrase,
                body=body,
                headers=response.headers,
                method="GET",
                path=path,
                target=target,
                now=self._clock(),
            )
            logger.warning(
                "proxmox.request_failed",
                method="GET",
                path=path,
                status=response.status_code,
                error=type(error).__name__,
                target=target,
            )
            raise error
        if not isinstance(body, dict) or "data" not in body:
            raise UnexpectedResponse(
                f"Proxmox returned an unreadable body for GET {path}", target=target
            )
        return cast(dict[str, Any], body)

    def _timeout_with_read(self, read: float) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self._timeout.connect,
            read=read,
            write=self._timeout.write,
            pool=self._timeout.pool,
        )

    @staticmethod
    def _json_or_none(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None

    def _transport_error(self, exc: httpx.TransportError, path: str) -> HarnessError:
        target = self._endpoint.host
        cause: BaseException | None = exc
        seen: set[int] = set()
        # Exception chains can be cyclic (an exception re-raised inside its own
        # handler), so walk each link once.
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, ssl.SSLCertVerificationError):
                return TlsVerificationFailed(
                    f"the Proxmox node's certificate failed verification on GET {path}",
                    target=target,
                )
            cause = cause.__cause__ or cause.__context__
        if isinstance(exc, httpx.TimeoutException):
            # Every call here is a read, so a timeout is not ambiguous: nothing changed.
            return TargetUnavailable(f"Proxmox did not answer in time on GET {path}", target=target)
        return TargetUnavailable(f"could not reach Proxmox on GET {path}", target=target)

    def _parse[M](self, path: str, parse: Callable[[], M]) -> M:
        try:
            return parse()
        except (ValidationError, KeyError, TypeError) as exc:
            # The validation error quotes the offending values (target content), so it
            # is not chained; only its size is logged.
            count = exc.error_count() if isinstance(exc, ValidationError) else 1
            logger.warning("proxmox.unexpected_shape", path=path, errors=count)
            raise UnexpectedResponse(
                f"Proxmox returned an unexpected shape for GET {path}", target=self._endpoint.host
            ) from None

    async def _get_list[M](
        self, path: str, build: Callable[[dict[str, Any]], M], **kwargs: Any
    ) -> Listing[M]:
        envelope = await self._get(path, **kwargs)
        as_of = self._clock()

        def parse() -> Listing[M]:
            rows = envelope["data"]
            if not isinstance(rows, list):
                raise TypeError("data is not a list")
            return Listing[M](
                items=[build(row) for row in cast(list[dict[str, Any]], rows)], as_of=as_of
            )

        return self._parse(path, parse)

    # -- version and cluster ---------------------------------------------------------

    async def version(self) -> Version:
        """``GET /version``: PVE version, release and repository ID."""
        envelope = await self._get("/version")
        return self._parse("/version", lambda: Version.model_validate(envelope["data"]))

    async def cluster_status(self) -> Listing[ClusterStatusEntry]:
        """``GET /cluster/status``: cluster name and quorum, plus one row per node."""
        return await self._get_list("/cluster/status", ClusterStatusEntry.model_validate)

    async def cluster_resources(
        self, resource_type: ResourceType | None = None
    ) -> Listing[Resource]:
        """``GET /cluster/resources``: every guest, node and storage with usage.

        Args:
            resource_type: Optional server-side filter.
        """
        params: dict[str, str | int] | None = (
            {"type": resource_type.value} if resource_type is not None else None
        )
        return await self._get_list("/cluster/resources", Resource.model_validate, params=params)

    async def ha_status(self) -> Listing[HaStatusEntry]:
        """``GET /cluster/ha/status/current``: HA manager, LRMs and services."""
        return await self._get_list("/cluster/ha/status/current", HaStatusEntry.model_validate)

    async def backup_jobs(self) -> Listing[BackupJob]:
        """``GET /cluster/backup``: scheduled vzdump jobs."""
        return await self._get_list("/cluster/backup", BackupJob.model_validate)

    async def list_pools(self, poolid: str | None = None) -> Listing[Pool]:
        """``GET /pools``: resource pools; with ``poolid``, that pool and its members.

        Args:
            poolid: Optional pool to read members of.
        """
        params: dict[str, str | int] | None = (
            {"poolid": identifiers.pool_id(poolid)} if poolid is not None else None
        )
        return await self._get_list("/pools", Pool.model_validate, params=params)

    # -- nodes -------------------------------------------------------------------------

    async def list_nodes(self) -> Listing[NodeSummary]:
        """``GET /nodes``: node names, online status and usage."""
        return await self._get_list("/nodes", NodeSummary.model_validate)

    async def node_status(self, node: str) -> NodeStatus:
        """``GET /nodes/{node}/status``: CPU, memory, uptime, kernel and PVE version."""
        path = f"/nodes/{_seg(identifiers.node_name(node))}/status"
        envelope = await self._get(path)
        as_of = self._clock()
        return self._parse(
            path, lambda: NodeStatus.model_validate({**envelope["data"], "as_of": as_of})
        )

    async def node_rrd(
        self,
        node: str,
        *,
        timeframe: RrdTimeframe = RrdTimeframe.HOUR,
        cf: RrdConsolidation = RrdConsolidation.AVERAGE,
    ) -> Listing[RrdPoint]:
        """``GET /nodes/{node}/rrddata``: node metrics time series.

        Args:
            node: Node name.
            timeframe: Window to read.
            cf: Consolidation function.
        """
        path = f"/nodes/{_seg(identifiers.node_name(node))}/rrddata"
        params: dict[str, str | int] = {"timeframe": timeframe.value, "cf": cf.value}
        return await self._get_list(path, RrdPoint.model_validate, params=params)

    async def network(self, node: str) -> NetworkConfig:
        """``GET /nodes/{node}/network``: interfaces and bridges, with any staged diff."""
        path = f"/nodes/{_seg(identifiers.node_name(node))}/network"
        envelope = await self._get(path)
        as_of = self._clock()

        def parse() -> NetworkConfig:
            changes = envelope.get("changes")
            return NetworkConfig(
                interfaces=[NetworkInterface.model_validate(row) for row in envelope["data"]],
                pending_changes=changes if isinstance(changes, str) and changes else None,
                as_of=as_of,
            )

        return self._parse(path, parse)

    # -- guests ------------------------------------------------------------------------

    async def list_guests(self, node: str, guest_type: GuestType) -> Listing[Guest]:
        """``GET /nodes/{node}/{qemu|lxc}``: guests of one type on one node."""
        node = identifiers.node_name(node)
        kind = _guest_type(guest_type)
        path = f"/nodes/{_seg(node)}/{kind}"
        return await self._get_list(
            path, lambda row: Guest.model_validate({**row, "type": kind, "node": node})
        )

    async def guest_config(self, node: str, vmid: int, guest_type: GuestType) -> GuestConfig:
        """``GET /nodes/{node}/{qemu|lxc}/{vmid}/config``: current config and its digest."""
        node = identifiers.node_name(node)
        kind = _guest_type(guest_type)
        vmid = identifiers.vmid(vmid)
        path = f"/nodes/{_seg(node)}/{kind}/{vmid}/config"
        envelope = await self._get(path)
        return self._parse(
            path,
            lambda: GuestConfig.from_api(vmid=vmid, type=kind, node=node, data=envelope["data"]),
        )

    async def guest_status(self, node: str, vmid: int, guest_type: GuestType) -> GuestStatus:
        """``GET /nodes/{node}/{qemu|lxc}/{vmid}/status/current``: run state, lock, HA."""
        kind = _guest_type(guest_type)
        path = (
            f"/nodes/{_seg(identifiers.node_name(node))}/{kind}/{identifiers.vmid(vmid)}"
            "/status/current"
        )
        envelope = await self._get(path)
        as_of = self._clock()
        return self._parse(
            path, lambda: GuestStatus.model_validate({**envelope["data"], "as_of": as_of})
        )

    # -- storage and disks -------------------------------------------------------------

    async def list_storage(self) -> Listing[StorageConfig]:
        """``GET /storage``: datacenter storage definitions."""
        return await self._get_list("/storage", StorageConfig.model_validate)

    async def storage_status(self, node: str, storage: str) -> StorageStatus:
        """``GET /nodes/{node}/storage/{storage}/status``: usage on one node."""
        path = (
            f"/nodes/{_seg(identifiers.node_name(node))}"
            f"/storage/{_seg(identifiers.storage_id(storage))}/status"
        )
        envelope = await self._get(path)
        as_of = self._clock()
        return self._parse(
            path, lambda: StorageStatus.model_validate({**envelope["data"], "as_of": as_of})
        )

    async def storage_content(
        self, node: str, storage: str, *, content: str | None = None
    ) -> Listing[StorageVolume]:
        """``GET /nodes/{node}/storage/{storage}/content``: volumes on a storage.

        Args:
            node: Node name.
            storage: Storage ID.
            content: Optional content-type filter (``images``, ``backup``, ``iso`` …).
        """
        path = (
            f"/nodes/{_seg(identifiers.node_name(node))}"
            f"/storage/{_seg(identifiers.storage_id(storage))}/content"
        )
        params: dict[str, str | int] | None = (
            {"content": identifiers.content_type(content)} if content is not None else None
        )
        return await self._get_list(path, StorageVolume.model_validate, params=params)

    async def list_disks(self, node: str, *, include_partitions: bool = True) -> Listing[Disk]:
        """``GET /nodes/{node}/disks/list``: physical disks with health and usage.

        Args:
            node: Node name.
            include_partitions: Also list partitions (needed to tell empty disks apart).
        """
        path = f"/nodes/{_seg(identifiers.node_name(node))}/disks/list"
        params: dict[str, str | int] = {"include-partitions": int(include_partitions)}
        return await self._get_list(
            path, Disk.model_validate, params=params, read_timeout=SLOW_READ_TIMEOUT
        )

    async def disk_smart(self, node: str, disk: str) -> SmartData:
        """``GET /nodes/{node}/disks/smart``: SMART health and attributes of one disk.

        Args:
            node: Node name.
            disk: Device path, for example ``/dev/sda``.
        """
        path = f"/nodes/{_seg(identifiers.node_name(node))}/disks/smart"
        envelope = await self._get(
            path, params={"disk": identifiers.disk_path(disk)}, read_timeout=SLOW_READ_TIMEOUT
        )
        return self._parse(path, lambda: SmartData.model_validate(envelope["data"]))

    # -- tasks -------------------------------------------------------------------------

    async def list_cluster_tasks(self) -> Listing[Task]:
        """``GET /cluster/tasks``: recent tasks across all nodes."""
        return await self._get_list("/cluster/tasks", Task.model_validate)

    async def list_node_tasks(
        self,
        node: str,
        *,
        typefilter: str | None = None,
        vmid: int | None = None,
        start: int = 0,
        limit: int = 50,
    ) -> Listing[Task]:
        """``GET /nodes/{node}/tasks``: task history of one node, newest first.

        Args:
            node: Node name.
            typefilter: Only tasks of this type, for example ``vzdump``.
            vmid: Only tasks about this guest.
            start: Offset for paging.
            limit: Page size.
        """
        if typefilter is not None and re.fullmatch(r"[a-z][a-z0-9_\-]*", typefilter) is None:
            raise InvalidInput("invalid task type filter")
        if start < 0 or not 0 < limit <= 1000:
            raise InvalidInput("invalid task paging")
        params: dict[str, str | int] = {"start": start, "limit": limit}
        if typefilter is not None:
            params["typefilter"] = typefilter
        if vmid is not None:
            params["vmid"] = identifiers.vmid(vmid)
        path = f"/nodes/{_seg(identifiers.node_name(node))}/tasks"
        return await self._get_list(path, Task.model_validate, params=params)

    @staticmethod
    def _upid(upid: Upid | str) -> Upid:
        return parse_upid(upid) if isinstance(upid, str) else upid

    async def task_status(self, upid: Upid | str) -> TaskStatus:
        """``GET /nodes/{node}/tasks/{upid}/status``, routed to the node in the UPID."""
        task = self._upid(upid)
        path = f"/nodes/{_seg(task.node)}/tasks/{_seg(str(task))}/status"
        envelope = await self._get(path)
        return self._parse(path, lambda: TaskStatus.model_validate(envelope["data"]))

    async def task_log(self, upid: Upid | str, *, start: int = 0, limit: int = 500) -> TaskLog:
        """``GET /nodes/{node}/tasks/{upid}/log``: a window of the task log.

        Args:
            upid: The task.
            start: First line offset (0-based), for incremental reads.
            limit: Maximum lines to return.
        """
        if start < 0 or not 0 < limit <= 5000:
            raise InvalidInput("invalid task log window")
        task = self._upid(upid)
        path = f"/nodes/{_seg(task.node)}/tasks/{_seg(str(task))}/log"
        envelope = await self._get(path, params={"start": start, "limit": limit})

        def parse() -> TaskLog:
            total = envelope.get("total")
            return TaskLog(
                lines=[TaskLogLine.model_validate(row) for row in envelope["data"]],
                total=total if isinstance(total, int) else None,
            )

        return self._parse(path, parse)
