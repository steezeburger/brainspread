import uuid as uuid_lib

from django.test import SimpleTestCase

from knowledge.models import Block
from knowledge.services.automation_spec import (
    SCHEDULE_CRON,
    SCHEDULE_DAILY,
    SCHEDULE_HOURLY,
    SCHEDULE_WEEKLY,
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULE,
    AutomationSpecError,
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

    def test_unsupported_query_form_is_rejected(self):
        with self.assertRaises(AutomationSpecError) as ctx:
            parse_automation_block(
                _block(
                    {
                        "trigger": "manual",
                        "action": "move_to_daily today",
                        "query": "tag:sticky",
                    }
                )
            )
        self.assertIn("query", "; ".join(ctx.exception.errors))

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
