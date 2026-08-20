import uuid as uuid_lib
from datetime import datetime
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase

from knowledge.commands import RunDueAutomationsCommand
from knowledge.forms.run_due_automations_form import RunDueAutomationsForm
from knowledge.models import AutomationRun
from knowledge.repositories import AutomationRunRepository, SavedViewRepository

from ..helpers import BlockFactory, PageFactory, UserFactory

UTC = dt_timezone.utc

TODOS_FILTER = {"block_type": {"in": ["todo"]}}


class TestRunDueAutomationsCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(timezone="UTC")
        cls.tag_page = PageFactory(user=cls.user, title="automation", slug="automation")
        SavedViewRepository.create(
            user=cls.user,
            name="Todos",
            slug="todos",
            filter_spec=TODOS_FILTER,
            sort=[],
        )

    def _automation(self, **props):
        page = PageFactory(
            user=self.user,
            title="Automations",
            slug=f"autos-{uuid_lib.uuid4().hex[:8]}",
        )
        block = BlockFactory(
            user=self.user,
            page=page,
            content="Tick automation #automation",
            properties=props,
        )
        block.pages.add(self.tag_page)
        return block

    def _tick(self, now=None):
        form = RunDueAutomationsForm({"now": now} if now else {})
        self.assertTrue(form.is_valid(), form.errors)
        return RunDueAutomationsCommand(form).execute()

    def test_fires_due_scheduled_automation(self):
        notes = PageFactory(user=self.user, title="Notes", slug="notes")
        todo = BlockFactory(
            user=self.user, page=notes, block_type="todo", content="TODO x"
        )
        automation = self._automation(
            trigger="schedule every 15m",
            query="view:todos",
            action="set_type done",
            allow="set_type",
        )

        result = self._tick(now=datetime(2026, 6, 27, 10, 7, tzinfo=UTC))

        self.assertEqual(result["fired"], 1)
        todo.refresh_from_db()
        self.assertEqual(todo.block_type, "done")
        run = AutomationRun.objects.get(automation_block_uuid=automation.uuid)
        self.assertEqual(run.status, AutomationRun.STATUS_SUCCEEDED)
        self.assertEqual(run.trigger, AutomationRun.TRIGGER_SCHEDULE)

    def test_recently_run_automation_is_not_refired(self):
        automation = self._automation(
            trigger="schedule every 15m",
            query="view:todos",
            action="set_type done",
            allow="set_type",
        )
        now = datetime(2026, 6, 27, 10, 7, tzinfo=UTC)
        # Ran just after the 10:00 slot — not due again until 10:15.
        AutomationRunRepository.create(
            user=self.user,
            automation_block_uuid=str(automation.uuid),
            trigger=AutomationRun.TRIGGER_SCHEDULE,
            status=AutomationRun.STATUS_SUCCEEDED,
            started_at=datetime(2026, 6, 27, 10, 1, tzinfo=UTC),
        )

        result = self._tick(now=now)

        self.assertEqual(result["fired"], 0)
        self.assertEqual(result["skipped"], 1)

    def test_manual_and_disabled_automations_are_skipped(self):
        self._automation(trigger="manual", action="set_type done", allow="set_type")
        self._automation(
            trigger="schedule every 15m",
            query="view:todos",
            action="set_type done",
            allow="set_type",
            enabled="false",
        )

        result = self._tick(now=datetime(2026, 6, 27, 10, 7, tzinfo=UTC))

        self.assertEqual(result["fired"], 0)
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(AutomationRun.objects.count(), 0)

    def test_malformed_spec_records_one_failed_run_then_dedupes(self):
        automation = self._automation(trigger="schedule every 15m")  # no action::

        first = self._tick(now=datetime(2026, 6, 27, 10, 7, tzinfo=UTC))
        second = self._tick(now=datetime(2026, 6, 27, 10, 8, tzinfo=UTC))

        self.assertEqual(first["failed_parse"], 1)
        self.assertEqual(second["failed_parse"], 0)
        runs = AutomationRun.objects.filter(automation_block_uuid=automation.uuid)
        self.assertEqual(runs.count(), 1)
        self.assertEqual(runs.first().status, AutomationRun.STATUS_FAILED)

    def test_claim_carries_pinned_now_as_started_at(self):
        automation = self._automation(
            trigger="schedule every 15m",
            query="view:todos",
            action="set_type done",
        )
        pinned = datetime(2026, 6, 27, 10, 7, tzinfo=UTC)

        self._tick(now=pinned)

        run = AutomationRun.objects.get(automation_block_uuid=automation.uuid)
        self.assertEqual(run.started_at, pinned)

    @patch(
        "knowledge.commands.run_due_automations_command."
        "RunDueAutomationsCommand._execute"
    )
    def test_stranded_claim_prevents_slot_refire(self, mock_execute):
        # Claim-then-execute contract: if execution dies after the claim
        # transaction commits, the RUNNING claim still marks the slot as
        # taken — the next tick must not double-fire it.
        automation = self._automation(
            trigger="schedule every 15m",
            query="view:todos",
            action="set_type done",
        )

        first = self._tick(now=datetime(2026, 6, 27, 10, 7, tzinfo=UTC))
        second = self._tick(now=datetime(2026, 6, 27, 10, 9, tzinfo=UTC))

        self.assertEqual(first["fired"], 1)
        self.assertEqual(second["fired"], 0)
        runs = AutomationRun.objects.filter(automation_block_uuid=automation.uuid)
        self.assertEqual(runs.count(), 1)
        self.assertEqual(runs.first().status, AutomationRun.STATUS_RUNNING)
        mock_execute.assert_called_once()

    def test_template_page_automation_never_fires(self):
        template = PageFactory(
            user=self.user,
            title="Pack",
            slug="pack",
            page_type="template",
        )
        block = BlockFactory(
            user=self.user,
            page=template,
            content="Dormant #automation",
            properties={
                "trigger": "schedule every 15m",
                "query": "view:todos",
                "action": "set_type done",
                "allow": "set_type",
            },
        )
        block.pages.add(self.tag_page)

        result = self._tick(now=datetime(2026, 6, 27, 10, 7, tzinfo=UTC))

        self.assertEqual(result["considered"], 0)
        self.assertEqual(AutomationRun.objects.count(), 0)


class TestNotifyAction(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(timezone="UTC")
        cls.user.discord_webhook_url = "https://discord.example/hook"
        cls.user.discord_user_id = "12345"
        cls.user.save(update_fields=["discord_webhook_url", "discord_user_id"])
        cls.tag_page = PageFactory(user=cls.user, title="automation", slug="automation")
        SavedViewRepository.create(
            user=cls.user,
            name="Doing",
            slug="doing",
            filter_spec={"block_type": "doing"},
            sort=[],
        )

    def _automation(self, **props):
        page = PageFactory(
            user=self.user, title="Autos", slug=f"autos-{uuid_lib.uuid4().hex[:8]}"
        )
        block = BlockFactory(
            user=self.user,
            page=page,
            content="Nudge #automation",
            properties=props,
        )
        block.pages.add(self.tag_page)
        return block

    def _run_manual(self, automation):
        from knowledge.commands import RunAutomationCommand
        from knowledge.forms.run_automation_form import RunAutomationForm

        form = RunAutomationForm(
            {"user": self.user, "automation_block": automation.uuid}
        )
        self.assertTrue(form.is_valid(), form.errors)
        return RunAutomationCommand(form).execute()

    @patch("knowledge.services.automation_actions.post_webhook")
    def test_notify_sends_one_message_listing_matches(self, mock_post):
        from knowledge.services.discord_webhook import DiscordDeliveryResult

        mock_post.return_value = DiscordDeliveryResult(True, "")
        notes = PageFactory(user=self.user, title="Notes", slug="notes-n")
        BlockFactory(
            user=self.user, page=notes, block_type="doing", content="DOING ship"
        )
        automation = self._automation(
            trigger="schedule every 15m",
            query="view:doing",
            action='notify "still on this?"',
            allow="notify",
        )

        result = self._run_manual(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        self.assertEqual(result["result"]["affected"], 1)
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertIn("still on this?", kwargs["embeds"][0]["title"])
        self.assertIn("DOING ship", kwargs["embeds"][0]["description"])

    @patch("knowledge.services.automation_actions.post_webhook")
    def test_notify_stays_quiet_when_query_matches_nothing(self, mock_post):
        automation = self._automation(
            trigger="schedule every 15m",
            query="view:doing",
            action='notify "still on this?"',
            allow="notify",
        )

        result = self._run_manual(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        self.assertEqual(result["result"]["affected"], 0)
        mock_post.assert_not_called()

    @patch("knowledge.services.automation_actions.post_webhook")
    def test_notify_lines_deep_link_when_site_url_configured(self, mock_post):
        from django.test import override_settings

        from knowledge.services.discord_webhook import DiscordDeliveryResult

        mock_post.return_value = DiscordDeliveryResult(True, "")
        notes = PageFactory(user=self.user, title="Notes", slug="notes-link")
        doing = BlockFactory(
            user=self.user, page=notes, block_type="doing", content="DOING ship"
        )
        automation = self._automation(
            trigger="manual",
            query="view:doing",
            action='notify "still on this?"',
        )

        with override_settings(SITE_URL="http://testserver"):
            result = self._run_manual(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        _, kwargs = mock_post.call_args
        description = kwargs["embeds"][0]["description"]
        self.assertIn(
            f"[DOING ship](http://testserver/knowledge/page/notes-link/"
            f"#block-{doing.uuid})",
            description,
        )

    @patch("knowledge.services.automation_actions.post_webhook")
    def test_notify_without_query_sends_bare_message(self, mock_post):
        from knowledge.services.discord_webhook import DiscordDeliveryResult

        mock_post.return_value = DiscordDeliveryResult(True, "")
        automation = self._automation(
            trigger="schedule weekly sun 19:00",
            action='notify "take the bins out"',
            allow="notify",
        )

        result = self._run_manual(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertIn("take the bins out", kwargs["embeds"][0]["title"])

    def test_notify_without_webhook_config_fails_run(self):
        self.user.discord_webhook_url = ""
        self.user.save(update_fields=["discord_webhook_url"])
        automation = self._automation(
            trigger="manual",
            action='notify "hello"',
            allow="notify",
        )

        result = self._run_manual(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("webhook", result["last_error"])


class TestApplyTemplateAction(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(timezone="UTC")
        cls.tag_page = PageFactory(user=cls.user, title="automation", slug="automation")
        cls.template = PageFactory(
            user=cls.user,
            title="Morning Routine",
            slug="morning-routine",
            page_type="template",
        )
        BlockFactory(
            user=cls.user,
            page=cls.template,
            block_type="todo",
            content="TODO meditate",
            order=1,
        )
        BlockFactory(
            user=cls.user,
            page=cls.template,
            block_type="todo",
            content="TODO stretch",
            order=2,
        )

    def _run(self, automation):
        from knowledge.commands import RunAutomationCommand
        from knowledge.forms.run_automation_form import RunAutomationForm

        form = RunAutomationForm(
            {"user": self.user, "automation_block": automation.uuid}
        )
        self.assertTrue(form.is_valid(), form.errors)
        return RunAutomationCommand(form).execute()

    def _automation(self, action: str):
        page = PageFactory(
            user=self.user, title="Autos", slug=f"autos-{uuid_lib.uuid4().hex[:8]}"
        )
        block = BlockFactory(
            user=self.user,
            page=page,
            content="Routine #automation",
            properties={
                "trigger": "schedule daily 5:00",
                "action": action,
                "allow": "apply_template",
            },
        )
        block.pages.add(self.tag_page)
        return block

    def test_applies_template_to_todays_daily(self):
        automation = self._automation('apply_template "morning routine" to today')

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        self.assertEqual(result["result"]["affected"], 2)

        from knowledge.models import Page

        daily = Page.objects.get(
            user=self.user, page_type="daily", date=self.user.today()
        )
        contents = set(daily.blocks.values_list("content", flat=True))
        self.assertIn("TODO meditate", contents)
        self.assertIn("TODO stretch", contents)

    def test_template_resolves_by_slug_too(self):
        automation = self._automation('apply_template "morning-routine" to today')

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        self.assertEqual(result["result"]["affected"], 2)

    def test_missing_template_fails_run(self):
        automation = self._automation('apply_template "nonexistent pack"')

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("not found", result["last_error"])
