import unittest

from tools.registry import (
    ToolDef,
    UnknownToolError,
    _REGISTRY,
    get,
    get_schemas_for_planner,
    register,
)


def _make_tool(name="test.tool", description="a test tool", requires_confirmation=False):
    async def fn(**kwargs):
        return "result"

    return ToolDef(
        name=name,
        description=description,
        params_schema={"type": "object", "properties": {}},
        fn=fn,
        requires_confirmation=requires_confirmation,
    )


class ToolRegistryTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(_REGISTRY)

    def tearDown(self):
        _REGISTRY.clear()
        _REGISTRY.update(self._saved)

    def test_register_and_get(self):
        tool = _make_tool("my.tool")
        register(tool)
        self.assertIs(get("my.tool"), tool)

    def test_get_unknown_raises_unknown_tool_error(self):
        with self.assertRaises(UnknownToolError):
            get("does.not.exist")

    def test_error_message_lists_available_tools(self):
        register(_make_tool("available.tool"))
        try:
            get("missing.tool")
        except UnknownToolError as e:
            self.assertIn("available.tool", str(e))

    def test_register_overwrites_existing(self):
        tool_a = _make_tool("dup.tool", description="first")
        tool_b = _make_tool("dup.tool", description="second")
        register(tool_a)
        register(tool_b)
        self.assertIs(get("dup.tool"), tool_b)

    def test_get_schemas_for_planner_format(self):
        register(_make_tool("schema.tool", description="does stuff"))
        schemas = get_schemas_for_planner()
        names = [s["name"] for s in schemas]
        self.assertIn("schema.tool", names)
        schema = next(s for s in schemas if s["name"] == "schema.tool")
        self.assertEqual(schema["description"], "does stuff")
        self.assertIn("params", schema)

    def test_requires_confirmation_preserved(self):
        register(_make_tool("confirm.tool", requires_confirmation=True))
        self.assertTrue(get("confirm.tool").requires_confirmation)
