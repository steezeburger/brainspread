from datetime import date, timedelta

from django.test import SimpleTestCase

from core.llm_tools import (
    Tool,
    ToolContext,
    ToolError,
    ToolRegistry,
    parse_relative_date,
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


class ParseRelativeDateTestCase(SimpleTestCase):
    TODAY = date(2026, 6, 20)

    def test_none_and_empty_return_none(self):
        self.assertIsNone(parse_relative_date(None, self.TODAY))
        self.assertIsNone(parse_relative_date("", self.TODAY))
        self.assertIsNone(parse_relative_date("   ", self.TODAY))

    def test_named_tokens(self):
        self.assertEqual(parse_relative_date("today", self.TODAY), self.TODAY)
        self.assertEqual(parse_relative_date("tomorrow", self.TODAY), date(2026, 6, 21))
        self.assertEqual(
            parse_relative_date("yesterday", self.TODAY), date(2026, 6, 19)
        )

    def test_offset_tokens(self):
        self.assertEqual(parse_relative_date("+7d", self.TODAY), date(2026, 6, 27))
        self.assertEqual(parse_relative_date("-3d", self.TODAY), date(2026, 6, 17))
        self.assertEqual(parse_relative_date("+2w", self.TODAY), date(2026, 7, 4))
        self.assertEqual(parse_relative_date("-1w", self.TODAY), date(2026, 6, 13))

    def test_iso_string(self):
        self.assertEqual(
            parse_relative_date("2027-01-15", self.TODAY), date(2027, 1, 15)
        )

    def test_date_passthrough(self):
        self.assertEqual(
            parse_relative_date(date(2030, 1, 1), self.TODAY), date(2030, 1, 1)
        )

    # -- weekday tokens (#220) ---------------------------------------------
    #
    # TODAY is a Saturday, so the "skips today" rule and the Monday-anchored
    # `this` week both have a visible effect here.

    def test_bare_weekday_is_next_occurrence(self):
        self.assertEqual(parse_relative_date("monday", self.TODAY), date(2026, 6, 22))
        self.assertEqual(parse_relative_date("friday", self.TODAY), date(2026, 6, 26))
        self.assertEqual(parse_relative_date("sunday", self.TODAY), date(2026, 6, 21))

    def test_weekday_abbreviations(self):
        self.assertEqual(parse_relative_date("mon", self.TODAY), date(2026, 6, 22))
        self.assertEqual(parse_relative_date("next fri", self.TODAY), date(2026, 6, 26))
        self.assertEqual(parse_relative_date("last sun", self.TODAY), date(2026, 6, 14))

    def test_weekday_tokens_are_case_and_space_insensitive(self):
        self.assertEqual(
            parse_relative_date("  Next   Monday ", self.TODAY), date(2026, 6, 22)
        )

    def test_next_weekday_matches_bare_form(self):
        for name in ("monday", "wednesday", "saturday"):
            with self.subTest(name=name):
                self.assertEqual(
                    parse_relative_date(f"next {name}", self.TODAY),
                    parse_relative_date(name, self.TODAY),
                )

    def test_last_weekday_is_previous_occurrence(self):
        self.assertEqual(
            parse_relative_date("last monday", self.TODAY), date(2026, 6, 15)
        )
        self.assertEqual(
            parse_relative_date("last friday", self.TODAY), date(2026, 6, 19)
        )

    def test_this_weekday_is_monday_anchored_and_may_be_past(self):
        # This week's Monday (2026-06-15) is behind TODAY's Saturday.
        self.assertEqual(
            parse_relative_date("this monday", self.TODAY), date(2026, 6, 15)
        )
        self.assertEqual(parse_relative_date("this saturday", self.TODAY), self.TODAY)
        self.assertEqual(
            parse_relative_date("this sunday", self.TODAY), date(2026, 6, 21)
        )

    def test_same_weekday_skips_today(self):
        # The motivating case: asking for a Monday while running on a
        # Monday must land on the *next* one, not today.
        monday = date(2026, 6, 15)
        self.assertEqual(parse_relative_date("monday", monday), date(2026, 6, 22))
        self.assertEqual(parse_relative_date("next monday", monday), date(2026, 6, 22))
        self.assertEqual(parse_relative_date("last monday", monday), date(2026, 6, 8))
        self.assertEqual(parse_relative_date("this monday", monday), monday)

    def test_every_weekday_from_every_day_of_the_week(self):
        names = [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ]
        # A full Mon-Sun week of run dates.
        week = [date(2026, 6, 15) + timedelta(days=i) for i in range(7)]
        for today in week:
            for target, name in enumerate(names):
                with self.subTest(today=today, name=name):
                    ahead = parse_relative_date(name, today)
                    self.assertEqual(ahead.weekday(), target)
                    self.assertIn((ahead - today).days, range(1, 8))

                    behind = parse_relative_date(f"last {name}", today)
                    self.assertEqual(behind.weekday(), target)
                    self.assertIn((today - behind).days, range(1, 8))

                    current = parse_relative_date(f"this {name}", today)
                    self.assertEqual(current.weekday(), target)
                    self.assertEqual(
                        current - timedelta(days=target),
                        today - timedelta(days=today.weekday()),
                    )

    def test_garbage_raises_value_error(self):
        with self.assertRaises(ValueError):
            parse_relative_date("next thursdayy", self.TODAY)
        with self.assertRaises(ValueError):
            parse_relative_date("+5x", self.TODAY)
        # A qualifier on its own, or an unknown one, is not a weekday.
        with self.assertRaises(ValueError):
            parse_relative_date("next", self.TODAY)
        with self.assertRaises(ValueError):
            parse_relative_date("every monday", self.TODAY)
        with self.assertRaises(ValueError):
            parse_relative_date("next next monday", self.TODAY)

    def test_error_message_lists_weekday_shapes(self):
        with self.assertRaises(ValueError) as ctx:
            parse_relative_date("someday", self.TODAY)
        self.assertIn("next monday", str(ctx.exception))
