import uuid as uuid_lib
from datetime import timedelta

from django.test import SimpleTestCase

from knowledge.models import Block
from knowledge.services.automation_spec import (
    MAX_FOR_ITEMS,
    SCHEDULE_CRON,
    SCHEDULE_DAILY,
    SCHEDULE_EVERY,
    SCHEDULE_HOURLY,
    SCHEDULE_WEEKLY,
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULE,
    WHEN_BECOMES_EMPTY,
    WHEN_BECOMES_NONEMPTY,
    WHEN_COUNT,
    WHEN_MATCHED_FOR,
    AutomationSpecError,
    is_automation_content,
    parse_automation_block,
)


def _block(properties: dict, content: str = "My automation #automation") -> Block:
    return Block(uuid=uuid_lib.uuid4(), content=content, properties=properties)


class TestParseAutomationBlock(SimpleTestCase):
    def test_parses_daily_schedule_command_automation(self):
        spec = parse_automation_block(
            _block(
                {
                    "trigger": "schedule daily 6:00",
                    "query": "view:sticky-todos",
                    "action": "move_to_daily today",
                    "allow": "move_to_daily",
                    "enabled": "true",
                }
            )
        )

        self.assertEqual(spec.trigger.kind, TRIGGER_SCHEDULE)
        self.assertEqual(spec.trigger.schedule.kind, SCHEDULE_DAILY)
        self.assertEqual(spec.trigger.schedule.hour, 6)
        self.assertEqual(spec.trigger.schedule.minute, 0)
        self.assertEqual(spec.query.view_slug, "sticky-todos")
        self.assertEqual(spec.action.verb, "move_to_daily")
        self.assertEqual(spec.action.args, ("today",))
        self.assertIn("move_to_daily", spec.allow)
        self.assertTrue(spec.enabled)

    def test_derives_name_and_slug_from_first_line(self):
        spec = parse_automation_block(
            _block(
                {"trigger": "manual", "action": "move_to_daily today"},
                content="Morning sticky sweep #automation\ntrigger:: manual",
            )
        )
        self.assertEqual(spec.name, "Morning sticky sweep")
        self.assertEqual(spec.slug, "morning-sticky-sweep")

    def test_parses_manual_trigger(self):
        spec = parse_automation_block(
            _block({"trigger": "manual", "action": "set_type done"})
        )
        self.assertEqual(spec.trigger.kind, TRIGGER_MANUAL)
        self.assertIsNone(spec.trigger.schedule)

    def test_parses_hourly_weekly_and_cron_cadences(self):
        hourly = parse_automation_block(
            _block({"trigger": "schedule hourly", "action": "set_type done"})
        )
        self.assertEqual(hourly.trigger.schedule.kind, SCHEDULE_HOURLY)

        weekly = parse_automation_block(
            _block({"trigger": "schedule weekly mon 9:00", "action": "set_type done"})
        )
        self.assertEqual(weekly.trigger.schedule.kind, SCHEDULE_WEEKLY)
        self.assertEqual(weekly.trigger.schedule.weekday, 0)
        self.assertEqual(weekly.trigger.schedule.hour, 9)

        cron = parse_automation_block(
            _block({"trigger": "schedule cron 0 6 * * 1", "action": "set_type done"})
        )
        self.assertEqual(cron.trigger.schedule.kind, SCHEDULE_CRON)
        self.assertEqual(cron.trigger.schedule.cron, "0 6 * * 1")

    def test_parses_every_cadence(self):
        minutes = parse_automation_block(
            _block({"trigger": "schedule every 15m", "action": "set_type done"})
        )
        self.assertEqual(minutes.trigger.schedule.kind, SCHEDULE_EVERY)
        self.assertEqual(minutes.trigger.schedule.interval_minutes, 15)

        hours = parse_automation_block(
            _block({"trigger": "schedule every 2h", "action": "set_type done"})
        )
        self.assertEqual(hours.trigger.schedule.interval_minutes, 120)

        with self.assertRaises(AutomationSpecError):
            parse_automation_block(
                _block({"trigger": "schedule every banana", "action": "set_type done"})
            )

    def test_quoted_prompt_action_is_one_arg(self):
        spec = parse_automation_block(
            _block(
                {
                    "trigger": "manual",
                    "action": 'prompt "add a child block with macros"',
                }
            )
        )
        self.assertEqual(spec.action.verb, "prompt")
        self.assertEqual(spec.action.args, ("add a child block with macros",))

    def test_enabled_defaults_true_and_false_is_honored(self):
        default_on = parse_automation_block(
            _block({"trigger": "manual", "action": "set_type done"})
        )
        self.assertTrue(default_on.enabled)

        off = parse_automation_block(
            _block({"trigger": "manual", "action": "set_type done", "enabled": "false"})
        )
        self.assertFalse(off.enabled)

    def test_allow_accepts_comma_or_space_separated(self):
        spec = parse_automation_block(
            _block(
                {
                    "trigger": "manual",
                    "action": "set_type done",
                    "allow": "move_to_daily, set_type create_block",
                }
            )
        )
        self.assertEqual(
            spec.allow, frozenset({"move_to_daily", "set_type", "create_block"})
        )

    def test_omitted_allow_is_none_not_empty(self):
        # None = "grant exactly the declared verb" downstream; an explicit
        # empty list would mean deny-all. The parser must keep them distinct.
        spec = parse_automation_block(
            _block({"trigger": "manual", "action": "set_type done"})
        )
        self.assertIsNone(spec.allow)

    def test_missing_trigger_and_action_are_reported_together(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(_block({}))
        joined = "; ".join(ctx.exception.errors)
        self.assertIn("trigger", joined)
        self.assertIn("action", joined)

    def test_bad_daily_time_is_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block({"trigger": "schedule daily 99:99", "action": "set_type done"})
            )
        self.assertIn("time", "; ".join(ctx.exception.errors))

    def test_unknown_trigger_is_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block({"trigger": "telepathy", "action": "set_type done"})
            )
        self.assertIn("telepathy", "; ".join(ctx.exception.errors))

    def test_inline_query_compiles_to_filter_spec(self):
        spec = parse_automation_block(
            _block(
                {
                    "trigger": "manual",
                    "action": "move_to_daily today",
                    "query": "tag:sticky and type:todo,doing",
                }
            )
        )
        self.assertEqual(spec.query.kind, "inline")
        self.assertEqual(
            spec.query.filter_spec,
            {
                "all": [
                    {"has_tag": "sticky"},
                    {"block_type": {"in": ["todo", "doing"]}},
                ]
            },
        )

    def test_malformed_inline_query_is_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block(
                    {
                        "trigger": "manual",
                        "action": "move_to_daily today",
                        "query": "due <",
                    }
                )
            )
        self.assertIn("query", "; ".join(ctx.exception.errors))

    def test_hashtag_in_query_is_rejected_with_guidance(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block(
                    {
                        "trigger": "manual",
                        "action": "move_to_daily today",
                        "query": "#sticky",
                    }
                )
            )
        self.assertIn("tag:", "; ".join(ctx.exception.errors))

    def test_bad_cron_arity_is_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block({"trigger": "schedule cron 0 6 *", "action": "set_type done"})
            )
        self.assertIn("cron", "; ".join(ctx.exception.errors))

    def test_non_string_property_values_are_coerced(self):
        # properties is a JSONField and set_property accepts any JSON
        # value — a bool stored programmatically must not crash the parser.
        spec = parse_automation_block(
            _block({"trigger": "manual", "action": "set_type done", "enabled": False})
        )
        self.assertFalse(spec.enabled)

    def test_non_string_trigger_fails_cleanly_not_with_a_crash(self):
        with self.assertRaises(AutomationSpecError):
            parse_automation_block(_block({"trigger": 5, "action": "set_type done"}))

    def test_quoted_arg_with_trailing_args_splits_shell_style(self):
        spec = parse_automation_block(
            _block({"trigger": "manual", "action": 'notify "still on this?" today'})
        )
        self.assertEqual(spec.action.verb, "notify")
        self.assertEqual(spec.action.args, ("still on this?", "today"))

    def test_multiple_quoted_args_stay_separate(self):
        spec = parse_automation_block(
            _block({"trigger": "manual", "action": 'prompt "a b" "c d"'})
        )
        self.assertEqual(spec.action.args, ("a b", "c d"))

    def test_unbalanced_quotes_are_a_spec_error(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block({"trigger": "manual", "action": 'notify "oops'})
            )
        self.assertIn("unbalanced", "; ".join(ctx.exception.errors))


class TestForDirective(SimpleTestCase):
    """`for::` iteration (issue #209): a literal list of items binding
    {{item}}, for standalone actions with no query::."""

    def test_comma_list_parses_ascending_integers(self):
        spec = parse_automation_block(
            _block(
                {
                    "trigger": "manual",
                    "for": "5,10,15,20,25,30",
                    "action": 'create_block "nudge {{item}}m" on today',
                }
            )
        )
        self.assertEqual(spec.for_spec.items, ("5", "10", "15", "20", "25", "30"))

    def test_range_form_expands_with_step(self):
        spec = parse_automation_block(
            _block(
                {
                    "trigger": "manual",
                    "for": "5..30 by 5",
                    "action": 'create_block "nudge {{item}}m" on today',
                }
            )
        )
        self.assertEqual(spec.for_spec.items, ("5", "10", "15", "20", "25", "30"))

    def test_range_form_tolerates_loose_spacing(self):
        spec = parse_automation_block(
            _block(
                {
                    "trigger": "manual",
                    "for": "5 .. 15 by 5",
                    "action": 'create_block "x {{item}}" on today',
                }
            )
        )
        self.assertEqual(spec.for_spec.items, ("5", "10", "15"))

    def test_no_for_prop_leaves_for_spec_none(self):
        spec = parse_automation_block(
            _block({"trigger": "manual", "action": "set_type done"})
        )
        self.assertIsNone(spec.for_spec)

    def test_empty_for_is_a_spec_error(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block(
                    {
                        "trigger": "manual",
                        "for": "",
                        "action": 'create_block "x" on today',
                    }
                )
            )
        self.assertIn("for::", "; ".join(ctx.exception.errors))

    def test_non_integer_items_are_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block(
                    {
                        "trigger": "manual",
                        "for": "a,b,c",
                        "action": 'create_block "x {{item}}" on today',
                    }
                )
            )
        self.assertIn("integers", "; ".join(ctx.exception.errors))

    def test_non_ascending_comma_list_is_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block(
                    {
                        "trigger": "manual",
                        "for": "10,5,20",
                        "action": 'create_block "x {{item}}" on today',
                    }
                )
            )
        self.assertIn("ascending", "; ".join(ctx.exception.errors))

    def test_duplicate_items_are_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block(
                    {
                        "trigger": "manual",
                        "for": "5,5,10",
                        "action": 'create_block "x {{item}}" on today',
                    }
                )
            )
        self.assertIn("ascending", "; ".join(ctx.exception.errors))

    def test_range_with_descending_bounds_is_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block(
                    {
                        "trigger": "manual",
                        "for": "30..5 by 5",
                        "action": 'create_block "x {{item}}" on today',
                    }
                )
            )
        self.assertIn("ascending", "; ".join(ctx.exception.errors))

    def test_range_step_must_be_at_least_one(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block(
                    {
                        "trigger": "manual",
                        "for": "5..10 by 0",
                        "action": 'create_block "x {{item}}" on today',
                    }
                )
            )
        self.assertIn("by", "; ".join(ctx.exception.errors))

    def test_over_cap_is_rejected(self):
        too_many = ",".join(str(n) for n in range(1, MAX_FOR_ITEMS + 3))
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block(
                    {
                        "trigger": "manual",
                        "for": too_many,
                        "action": 'create_block "x {{item}}" on today',
                    }
                )
            )
        self.assertIn("cap", "; ".join(ctx.exception.errors))

    def test_at_cap_is_accepted(self):
        exactly_cap = ",".join(str(n) for n in range(1, MAX_FOR_ITEMS + 1))
        spec = parse_automation_block(
            _block(
                {
                    "trigger": "manual",
                    "for": exactly_cap,
                    "action": 'create_block "x {{item}}" on today',
                }
            )
        )
        self.assertEqual(len(spec.for_spec.items), MAX_FOR_ITEMS)

    def test_for_and_query_together_are_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block(
                    {
                        "trigger": "manual",
                        "for": "5,10",
                        "query": "type:todo",
                        "action": 'create_block "x {{item}}" on today',
                    }
                )
            )
        self.assertIn("mutually exclusive", "; ".join(ctx.exception.errors))


class TestTokenSpecContracts(SimpleTestCase):
    """The two token/spec validations automation_spec enforces without
    needing the verb registry (issue #209 stories 10/11) — everything
    else about tokens is a run-time ActionError."""

    def test_block_tokens_without_query_are_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block(
                    {
                        "trigger": "manual",
                        "action": "move_to_page {{block.tag}}",
                    }
                )
            )
        self.assertIn("query::", "; ".join(ctx.exception.errors))

    def test_block_tokens_with_query_are_accepted(self):
        spec = parse_automation_block(
            _block(
                {
                    "trigger": "manual",
                    "query": "type:todo",
                    "action": "move_to_page {{block.tag}}",
                }
            )
        )
        self.assertEqual(spec.action.args, ("{{block.tag}}",))

    def test_item_without_for_is_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block(
                    {
                        "trigger": "manual",
                        "action": 'create_block "x {{item}}" on today',
                    }
                )
            )
        self.assertIn("for::", "; ".join(ctx.exception.errors))

    def test_item_with_for_is_accepted(self):
        spec = parse_automation_block(
            _block(
                {
                    "trigger": "manual",
                    "for": "5,10",
                    "action": 'create_block "x {{item}}" on today',
                }
            )
        )
        self.assertIsNotNone(spec.for_spec)


class TestParseWhenAndWatch(SimpleTestCase):
    """`when::` / `watch::` reactive-slice parsing (issue #206)."""

    def _spec(self, **props):
        base = {
            "trigger": "schedule every 5m",
            "query": "type:todo",
            "action": "set_type doing",
        }
        base.update(props)
        return parse_automation_block(_block(base))

    def test_becomes_empty_parses(self):
        spec = self._spec(when="becomes-empty")
        self.assertEqual(spec.when.kind, WHEN_BECOMES_EMPTY)
        self.assertIsNone(spec.when.threshold)

    def test_becomes_nonempty_parses(self):
        spec = self._spec(when="becomes-nonempty")
        self.assertEqual(spec.when.kind, WHEN_BECOMES_NONEMPTY)

    def test_count_condition_parses_op_and_threshold(self):
        spec = self._spec(when="count > 5")
        self.assertEqual(spec.when.kind, WHEN_COUNT)
        self.assertEqual(spec.when.op, ">")
        self.assertEqual(spec.when.threshold, 5)

    def test_count_condition_accepts_all_comparison_ops(self):
        for op in ("<", "<=", ">", ">="):
            spec = self._spec(when=f"count {op} 3")
            self.assertEqual(spec.when.op, op, msg=op)

    def test_count_condition_without_spaces_parses(self):
        spec = self._spec(when="count>=10")
        self.assertEqual(spec.when.op, ">=")
        self.assertEqual(spec.when.threshold, 10)

    def test_matched_for_parses_minutes_hours_days(self):
        self.assertEqual(
            self._spec(when="matched-for 30m").when.duration, timedelta(minutes=30)
        )
        self.assertEqual(
            self._spec(when="matched-for 2h").when.duration, timedelta(hours=2)
        )
        self.assertEqual(
            self._spec(when="matched-for 3d").when.duration, timedelta(days=3)
        )
        self.assertEqual(self._spec(when="matched-for 2h").when.kind, WHEN_MATCHED_FOR)

    def test_matched_for_under_a_minute_is_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            self._spec(when="matched-for 30s")
        self.assertIn("unknown", "; ".join(ctx.exception.errors))

    def test_unknown_when_condition_is_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            self._spec(when="becomes-purple")
        self.assertIn("unknown", "; ".join(ctx.exception.errors))

    def test_when_without_query_is_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block(
                    {
                        "trigger": "manual",
                        "action": "set_type doing",
                        "when": "becomes-empty",
                    }
                )
            )
        self.assertIn("query::", "; ".join(ctx.exception.errors))

    def test_watch_parses_field_and_tag_and_property_tokens(self):
        spec = self._spec(
            when="matched-for 2h", watch="due, tag:priority property:size"
        )
        self.assertEqual(
            spec.watch, frozenset({"due", "tag:priority", "property:size"})
        )

    def test_watch_without_matched_for_is_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            self._spec(when="becomes-empty", watch="due")
        self.assertIn("watch::", "; ".join(ctx.exception.errors))

    def test_watch_bad_token_is_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            self._spec(when="matched-for 2h", watch="bogus-thing")
        self.assertIn("bad `watch::` token", "; ".join(ctx.exception.errors))

    def test_when_and_watch_absent_by_default(self):
        spec = self._spec()
        self.assertIsNone(spec.when)
        self.assertIsNone(spec.watch)


class TestIsAutomationContent(SimpleTestCase):
    """Content-token resolution (issue #140) must skip automation
    definitions — their {{...}} are the automation vocabulary, resolved
    at run time by automation_actions, not at save time (issue #209)."""

    def test_hashtag_marks_content_as_automation(self):
        self.assertTrue(
            is_automation_content("Ping sweep #automation\ntrigger:: manual", "daily")
        )

    def test_automations_page_marks_content_as_automation_without_hashtag(self):
        self.assertTrue(is_automation_content("trigger:: manual", "automation"))

    def test_plain_content_is_not_automation(self):
        self.assertFalse(is_automation_content("standup notes {{today}}", "daily"))

    def test_escaped_hashtag_does_not_count(self):
        self.assertFalse(
            is_automation_content(r"write \#automation literally", "daily")
        )
