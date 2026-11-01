"""The tool decorator, the manifest parser and the Capability checks."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

from homelab_harness_sdk import (
    Capability,
    Credential,
    Manifest,
    TargetConfig,
    ToolInput,
    ToolOutput,
    Untrusted,
    read_tool,
)

MANIFEST = """
name = "demo"
version = "0.1.0"
description = "demo"
[credentials.read]
[tools]
"demo.thing.get" = { credential = "read" }
"""


class Args(ToolInput):
    key: str


class Text(Untrusted):
    note: str


class Plain(ToolOutput):
    value: int


class WithText(ToolOutput):
    untrusted: Text


@read_tool(name="demo.thing.get", credential="read", title="Get a thing")
async def get_thing(ctx, args: Args) -> WithText:
    """Return a thing."""
    return WithText(as_of=ctx.now(), untrusted=Text(note=args.key))


@asynccontextmanager
async def _connect(_target, _credential):
    yield None


async def _probe(_adapter):
    return None


def _capability(*tools, manifest=MANIFEST):
    return Capability(
        manifest=Manifest.parse(manifest),
        target_model=TargetConfig,
        connect=_connect,
        probe=_probe,
        tools=tools,
    )


def test_decorator_derives_models_and_description():
    assert get_thing.input_model is Args
    assert get_thing.output_model is WithText
    assert get_thing.description == "Return a thing."
    assert get_thing.kind == "read"
    assert get_thing.open_world is False
    assert get_thing.returns_untrusted is True
    assert get_thing.input_schema()["additionalProperties"] is False


async def test_tool_call_runs_the_function():
    class Ctx:
        targets = ("t",)

        def now(self):
            return datetime(2026, 11, 1, tzinfo=UTC)

    out = await get_thing(Ctx(), Args(key="k"))
    assert out.untrusted.note == "k"


def test_plain_outputs_are_not_flagged_untrusted():
    @read_tool(name="demo.plain.get", credential="read", title="Plain")
    async def plain(ctx, args: Args) -> Plain:
        """Plain."""
        return Plain(as_of=ctx.now(), value=1)

    assert plain.returns_untrusted is False


@pytest.mark.parametrize("name", ["demo", "demo.get", "Demo.thing.get", "demo..get"])
def test_bad_tool_names_are_refused(name):
    with pytest.raises(TypeError, match=r"capability\.area\.verb"):
        read_tool(name=name, credential="read", title="x")


def test_missing_docstring_or_annotations_are_refused():
    with pytest.raises(TypeError, match="docstring"):

        @read_tool(name="demo.a.b", credential="read", title="x")
        async def undocumented(ctx, args: Args) -> Plain: ...

    with pytest.raises(TypeError, match="ToolInput"):

        @read_tool(name="demo.a.b", credential="read", title="x")
        async def untyped(ctx, args: dict) -> Plain:
            """Doc."""


def test_manifest_parses_tiers_and_tools():
    manifest = Manifest.parse(MANIFEST)
    assert manifest.credential_tiers == {"read"}
    assert dict(manifest.tools) == {"demo.thing.get": "read"}
    with pytest.raises(ValueError, match="missing"):
        Manifest.parse('name = "x"')


def test_capability_checks_tool_names_and_tiers():
    assert _capability(get_thing).name == "demo"
    with pytest.raises(ValueError, match="twice"):
        _capability(get_thing, get_thing)
    with pytest.raises(ValueError, match="undeclared tier"):
        _capability(get_thing, manifest=MANIFEST.replace("[credentials.read]", "[credentials.x]"))
    with pytest.raises(ValueError, match="must start with"):
        _capability(get_thing, manifest=MANIFEST.replace('name = "demo"', 'name = "other"'))


def test_credential_repr_hides_the_secret():
    secret = "CANARY_" + "c" * 16
    credential = Credential(tier="read", token_id="u@pve!read", secret=secret)
    assert secret not in repr(credential)
    assert secret not in str(credential)
