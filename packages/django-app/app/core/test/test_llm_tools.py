from django.test import SimpleTestCase

from core.llm_tools import (
    Tool,
    ToolContext,
    ToolError,
    ToolRegistry,
    to_anthropic,
    to_mcp,
    to_openai,
)


def _echo(ctx: ToolContext, args: dict) -> dict:
    return {"user_id": getattr(ctx.user, "id", ctx.user), "args": args}


def _read_tool(name: str = "read") -> Tool:
    return Tool(
        name=name,
        description="a read tool",
        input_schema={"type": "object", "properties": {}},
        handler=_echo,
    )


def _write_tool(name: str = "write") -> Tool:
    return Tool(
        name=name,
        description="a write tool",
        input_schema={"type": "object", "properties": {}},
        handler=_echo,
        is_write=True,
    )


class ToolRegistryTestCase(SimpleTestCase):
    def test_get_and_contains(self):
        tool = _read_tool()
        registry = ToolRegistry([tool])
        self.assertIs(registry.get("read"), tool)
        self.assertIn("read", registry)
        self.assertIsNone(registry.get("missing"))
        self.assertNotIn("missing", registry)

    def test_duplicate_name_rejected(self):
        with self.assertRaises(ValueError):
            ToolRegistry([_read_tool(), _read_tool()])

    def test_tools_filters_writes(self):
        registry = ToolRegistry([_read_tool(), _write_tool()])
        all_names = [t.name for t in registry.tools()]
        read_names = [t.name for t in registry.tools(include_writes=False)]
        self.assertEqual(all_names, ["read", "write"])
        self.assertEqual(read_names, ["read"])

    def test_execute_dispatches_to_handler(self):
        registry = ToolRegistry([_read_tool()])
        ctx = ToolContext(user=42)
        result = registry.execute("read", ctx, {"q": "hi"})
        self.assertEqual(result, {"user_id": 42, "args": {"q": "hi"}})

    def test_execute_unknown_raises_tool_error(self):
        registry = ToolRegistry([_read_tool()])
        ctx = ToolContext(user=1)
        with self.assertRaises(ToolError):
            registry.execute("nope", ctx, {})

    def test_context_carries_current_page_uuid(self):
        ctx = ToolContext(user=1, current_page_uuid="abc")
        self.assertEqual(ctx.current_page_uuid, "abc")
        # Defaults to None when omitted.
        self.assertIsNone(ToolContext(user=1).current_page_uuid)


class RenderersTestCase(SimpleTestCase):
    def setUp(self):
        self.tools = [_read_tool("alpha"), _write_tool("beta")]

    def test_to_anthropic(self):
        rendered = to_anthropic(self.tools)
        self.assertEqual(
            rendered[0],
            {
                "name": "alpha",
                "description": "a read tool",
                "input_schema": {"type": "object", "properties": {}},
            },
        )

    def test_to_openai(self):
        rendered = to_openai(self.tools)
        self.assertEqual(rendered[0]["type"], "function")
        self.assertEqual(rendered[0]["function"]["name"], "alpha")
        self.assertEqual(
            rendered[0]["function"]["parameters"],
            {"type": "object", "properties": {}},
        )

    def test_to_mcp_uses_camelcase_input_schema(self):
        rendered = to_mcp(self.tools)
        self.assertEqual(rendered[0]["name"], "alpha")
        self.assertIn("inputSchema", rendered[0])
        self.assertNotIn("input_schema", rendered[0])
