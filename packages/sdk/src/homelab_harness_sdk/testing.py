"""The capability contract test kit (docs/spec/extending.md).

Every capability runs it from one test file by subclassing
:class:`CapabilityContract`::

    class TestProxmoxContract(CapabilityContract):
        capability = CAPABILITY
        sample_arguments = {"proxmox.node.get": {"node": "pve1"}, ...}

        def open_adapter(self, secret):
            ...  # an adapter using `secret` as its credential; HTTP is mocked by the kit

        def install_routes(self, router, canary):
            ...  # success responses with `canary` planted in every sensitive field

The kit mocks all HTTP with ``respx``, so a capability whose adapter uses
``httpx`` needs no network. It checks, for every tool:

* metadata: a description, valid JSON Schemas, a ``read`` classification, and a
  credential tier that the manifest declares (and the manifest lists the tool);
* error mapping: 401, 403, 404, 409, 429, 500, 503, read timeout and connect
  failure become the shared ``homelab_harness_sdk.errors`` types, with messages
  that contain neither the response body nor the credential;
* redaction (R-16, R-34): with canaries planted in every response, no canary and
  no credential reaches a result, an error or a log line, and no output field
  is named like a secret;
* untrusted text (S7): text fields with telltale names (``name``,
  ``description``, ``notes`` …) sit inside an ``Untrusted`` envelope unless the
  capability declares them trusted, with a reason.

Install with the ``testing`` extra (``homelab-harness-sdk[testing]``).
"""

from __future__ import annotations

import logging
import re
import secrets
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, cast

import httpx
import jsonschema  # pyright: ignore[reportMissingTypeStubs]
import pytest
import respx
from structlog.testing import capture_logs

from homelab_harness_sdk.capability import Capability
from homelab_harness_sdk.errors import (
    AuthRejected,
    Conflict,
    HarnessError,
    InvalidInput,
    NotFound,
    PermissionDenied,
    RateLimited,
    TargetUnavailable,
)
from homelab_harness_sdk.tools import UNTRUSTED_SCHEMA_KEY, ReadTool

TEXT_FIELD_NAMES = frozenset(
    {"name", "description", "comment", "comments", "notes", "tags", "log", "text"}
)
"""Field names that usually hold target-written text and so belong in an envelope."""

# HTTP client libraries log request lines including the reason phrase, which some
# targets fill with error text. Core holds these loggers at WARNING; the kit
# checks the capability's own logging, not theirs.
_LIBRARY_LOGGERS = ("httpx", "httpcore")

_SECRET_FIELD = re.compile(r"secret|passw|token|private_?key|api_?key", re.IGNORECASE)


def make_canary(label: str) -> str:
    """Return a fresh ``CANARY_<label>_<hex>`` value; it never exists in the repository."""
    return f"CANARY_{label}_{secrets.token_hex(12)}"


@dataclass(frozen=True, slots=True)
class ErrorCase:
    """One failure the target can produce, and the shared error it must map to."""

    id: str
    expected: type[HarnessError]
    status: int | None = None
    exception: type[httpx.TransportError] | None = None

    def side_effect(self, body_canary: str) -> Callable[[httpx.Request], httpx.Response]:
        """Build a respx side effect producing this failure, with the canary in the body."""

        def respond(request: httpx.Request) -> httpx.Response:
            if self.exception is not None:
                raise self.exception(body_canary, request=request)
            assert self.status is not None
            return httpx.Response(
                self.status,
                json={"message": body_canary, "errors": {"field": body_canary}},
                headers={"Retry-After": "7"},
                extensions={"reason_phrase": body_canary.encode()},
            )

        return respond


ERROR_CASES: tuple[ErrorCase, ...] = (
    ErrorCase("401", AuthRejected, status=401),
    ErrorCase("403", PermissionDenied, status=403),
    ErrorCase("404", NotFound, status=404),
    ErrorCase("409", Conflict, status=409),
    ErrorCase("429", RateLimited, status=429),
    ErrorCase("500", TargetUnavailable, status=500),
    ErrorCase("503", TargetUnavailable, status=503),
    ErrorCase("read-timeout", TargetUnavailable, exception=httpx.ReadTimeout),
    ErrorCase("connect-error", TargetUnavailable, exception=httpx.ConnectError),
)


class _KitContext:
    """A ToolContext with one target whose adapter comes from the contract class."""

    def __init__(self, open_adapter: Callable[[], AbstractAsyncContextManager[Any]]) -> None:
        self._open = open_adapter

    @property
    def targets(self) -> Sequence[str]:
        return [CapabilityContract.target_name]

    def adapter(self, target: str | None = None) -> AbstractAsyncContextManager[Any]:
        if target not in (None, CapabilityContract.target_name):
            raise InvalidInput("unknown target")
        return self._open()

    def now(self) -> datetime:
        return datetime.now(UTC)


def _capability_log_text(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(
        record.getMessage()
        for record in caplog.records
        if not record.name.startswith(_LIBRARY_LOGGERS)
    )


def _schema_defs(schema: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    defs = cast(Mapping[str, Mapping[str, Any]], schema.get("$defs", {}))
    return {str(schema.get("title", "(root)")): schema, **defs}


def _properties(definition: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    return cast(Mapping[str, Mapping[str, Any]], definition.get("properties", {}))


def _is_text(prop: Mapping[str, Any]) -> bool:
    rendered = repr(prop)
    return "'string'" in rendered and "$ref" not in rendered


class CapabilityContract:
    """Base class for a capability's contract test (not collected by itself).

    Attributes:
        capability: The capability under test.
        sample_arguments: Valid arguments for every tool.
        tolerant_tools: Tools that report a target failure inside their result
            (for example a multi-target listing) instead of raising.
        trusted_text_fields: ``Model.field`` names exempt from the untrusted-text
            check, each with the reason it is not target-writable text.
        target_name: Name of the single target the kit's context exposes.
    """

    capability: ClassVar[Capability[Any, Any]]
    sample_arguments: ClassVar[Mapping[str, Mapping[str, Any]]]
    tolerant_tools: ClassVar[frozenset[str]] = frozenset()
    trusted_text_fields: ClassVar[Mapping[str, str]] = {}
    target_name: ClassVar[str] = "contract"

    def open_adapter(self, secret: str) -> AbstractAsyncContextManager[Any]:
        """Open an adapter whose credential secret is ``secret``. Override this."""
        raise NotImplementedError

    def install_routes(self, router: respx.MockRouter, canary: str) -> None:
        """Register success responses for every tool, planting ``canary``. Override this.

        Plant it in every field the capability must mask (passwords, keys, …).
        """
        raise NotImplementedError

    # -- helpers -------------------------------------------------------------------------

    def _tools(self) -> tuple[ReadTool[Any, Any, Any], ...]:
        return self.capability.tools

    def _context(self, secret: str) -> _KitContext:
        return _KitContext(lambda: self.open_adapter(secret))

    async def _call(self, tool: ReadTool[Any, Any, Any], secret: str) -> Any:
        args = tool.input_model.model_validate(self.sample_arguments[tool.name])
        return await tool(self._context(secret), args)

    # -- metadata ------------------------------------------------------------------------

    def test_tools_are_described(self) -> None:
        assert self._tools(), "a capability must offer at least one tool"
        for tool in self._tools():
            assert tool.description.strip(), f"{tool.name} has no description"
            assert tool.title.strip(), f"{tool.name} has no title"

    def test_schemas_are_valid_json_schema(self) -> None:
        for tool in self._tools():
            for schema in (tool.input_schema(), tool.output_schema()):
                jsonschema.Draft202012Validator.check_schema(schema)  # pyright: ignore[reportUnknownMemberType]
                assert schema.get("type") == "object", f"{tool.name}: schemas must be objects"
            assert "as_of" in _properties(tool.output_schema()), f"{tool.name}: no as_of"

    def test_every_tool_is_classified_as_read(self) -> None:
        # Plan tools arrive in Stage 2; until then every tool must be a read tool (S1).
        for tool in self._tools():
            assert isinstance(tool, ReadTool), f"{tool.name} is not a @read_tool"
            assert tool.kind == "read"

    def test_credential_tiers_match_the_manifest(self) -> None:
        manifest = self.capability.manifest
        declared = {tool.name: tool.credential for tool in self._tools()}
        assert declared == dict(manifest.tools), "manifest [tools] and the code disagree"
        for tool in self._tools():
            assert tool.credential in manifest.credential_tiers, tool.name

    def test_sample_arguments_cover_every_tool(self) -> None:
        names = {tool.name for tool in self._tools()}
        assert set(self.sample_arguments) == names
        for tool in self._tools():
            sample = self.sample_arguments[tool.name]
            jsonschema.validate(sample, tool.input_schema())  # pyright: ignore[reportUnknownMemberType]
            tool.input_model.model_validate(sample)

    def test_no_output_field_is_named_like_a_secret(self) -> None:
        # R-34: no tool returns a secret value, length or hash, so no field is named for one.
        for tool in self._tools():
            for model, definition in _schema_defs(tool.output_schema()).items():
                for field_name in _properties(definition):
                    assert not _SECRET_FIELD.search(field_name), (
                        f"{tool.name}: {model}.{field_name}"
                    )

    def test_target_text_is_inside_untrusted_envelopes(self) -> None:
        # S7: telltale text fields must be in an Untrusted envelope, or declared trusted.
        for tool in self._tools():
            for model, definition in _schema_defs(tool.output_schema()).items():
                if definition.get(UNTRUSTED_SCHEMA_KEY):
                    continue
                for field_name, prop in _properties(definition).items():
                    qualified = f"{model}.{field_name}"
                    if field_name in TEXT_FIELD_NAMES and _is_text(prop):
                        assert qualified in self.trusted_text_fields, (
                            f"{tool.name}: {qualified} looks like target text; move it into an "
                            "Untrusted envelope or list it in trusted_text_fields with a reason"
                        )

    # -- behaviour -----------------------------------------------------------------------

    async def test_results_validate_and_never_leak_canaries(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        secret = make_canary("SECRET")
        planted = make_canary("FIELD")
        caplog.set_level(logging.DEBUG)
        with respx.mock(assert_all_called=False) as router, capture_logs() as events:
            self.install_routes(router, planted)
            for tool in self._tools():
                output = await self._call(tool, secret)
                assert isinstance(output, tool.output_model), tool.name
                data = output.model_dump(mode="json")
                jsonschema.validate(data, tool.output_schema())  # pyright: ignore[reportUnknownMemberType]
                rendered = output.model_dump_json()
                assert secret not in rendered, f"{tool.name} returned the credential"
                assert planted not in rendered, f"{tool.name} returned a planted secret field"
        assert secret not in repr(events) and planted not in repr(events)
        logged = _capability_log_text(caplog)
        assert secret not in logged and planted not in logged

    @pytest.mark.parametrize("case", ERROR_CASES, ids=[c.id for c in ERROR_CASES])
    async def test_target_failures_map_to_shared_errors(
        self, case: ErrorCase, caplog: pytest.LogCaptureFixture
    ) -> None:
        secret = make_canary("SECRET")
        body = make_canary("BODY")
        caplog.set_level(logging.DEBUG)
        with respx.mock(assert_all_called=False) as router, capture_logs() as events:
            router.route().mock(side_effect=case.side_effect(body))
            for tool in self._tools():
                try:
                    output = await self._call(tool, secret)
                except HarnessError as exc:
                    assert isinstance(exc, case.expected), (
                        f"{tool.name}: {case.id} raised {type(exc).__name__}, "
                        f"expected {case.expected.__name__}"
                    )
                    for text in (exc.safe_message, str(exc), repr(exc)):
                        assert body not in text and secret not in text, tool.name
                    continue
                assert tool.name in self.tolerant_tools, (
                    f"{tool.name}: {case.id} did not raise; only tolerant_tools may report "
                    "failures in their result"
                )
                rendered = output.model_dump_json()
                assert body not in rendered and secret not in rendered, tool.name
        assert body not in repr(events) and secret not in repr(events)
        logged = _capability_log_text(caplog)
        assert body not in logged and secret not in logged
