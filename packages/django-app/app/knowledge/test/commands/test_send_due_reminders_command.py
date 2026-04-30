import os
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from knowledge.commands import SendDueRemindersCommand
from knowledge.forms import SendDueRemindersForm
from knowledge.models import Reminder
from knowledge.services.discord_webhook import DiscordDeliveryResult

from ..helpers import BlockFactory, PageFactory, UserFactory


def _ok(*_args, **_kwargs):
    return DiscordDeliveryResult(True, "")


def _fail(*_args, **_kwargs):
    return DiscordDeliveryResult(False, "boom")


@patch.dict(os.environ, {"ENVIRONMENT": "prod"})
class TestSendDueRemindersCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(
            discord_webhook_url="https://discord.com/api/webhooks/1/abc"
        )
        cls.page = PageFactory(user=cls.user)

    def _run(self):
        form = SendDueRemindersForm({})
        assert form.is_valid(), form.errors
        return SendDueRemindersCommand(form).execute()

    def test_sends_due_reminder_successfully(self):
        block = BlockFactory(user=self.user, page=self.page, content="TODO ship")
        reminder = Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        with patch("knowledge.commands.send_due_reminders_command.post_webhook", _ok):
            result = self._run()

        reminder.refresh_from_db()
        self.assertEqual(result["sent"], 1)
        self.assertEqual(reminder.status, Reminder.STATUS_SENT)
        self.assertIsNotNone(reminder.sent_at)

    def test_skips_reminder_when_block_is_completed(self):
        block = BlockFactory(
            user=self.user,
            page=self.page,
            content="DONE ship",
            block_type="done",
            completed_at=timezone.now(),
        )
        reminder = Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        # If the poster gets called, the test should fail.
        def _must_not_call(*a, **kw):
            raise AssertionError("deliver should not be called for completed blocks")

        with patch(
            "knowledge.commands.send_due_reminders_command.post_webhook",
            _must_not_call,
        ):
            result = self._run()

        reminder.refresh_from_db()
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(reminder.status, Reminder.STATUS_SKIPPED)

    def test_marks_reminder_failed_on_delivery_error(self):
        block = BlockFactory(user=self.user, page=self.page, content="TODO ship")
        reminder = Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        with patch("knowledge.commands.send_due_reminders_command.post_webhook", _fail):
            result = self._run()

        reminder.refresh_from_db()
        self.assertEqual(result["failed"], 1)
        self.assertEqual(reminder.status, Reminder.STATUS_FAILED)
        self.assertIn("boom", reminder.last_error)
        self.assertIsNone(reminder.sent_at)

    def test_ignores_not_yet_due_reminders(self):
        block = BlockFactory(user=self.user, page=self.page, content="TODO later")
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() + timedelta(minutes=5),
        )

        with patch("knowledge.commands.send_due_reminders_command.post_webhook", _ok):
            result = self._run()

        self.assertEqual(result["considered"], 0)
        self.assertEqual(result["sent"], 0)

    def test_ignores_already_sent_reminders(self):
        block = BlockFactory(user=self.user, page=self.page, content="TODO ship")
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=5),
            status=Reminder.STATUS_SENT,
            sent_at=timezone.now() - timedelta(minutes=4),
        )

        with patch("knowledge.commands.send_due_reminders_command.post_webhook", _ok):
            result = self._run()

        self.assertEqual(result["considered"], 0)

    def test_retries_previously_failed_reminder(self):
        """A previously-failed row (sent_at still NULL) retries on each tick
        and becomes sent when delivery succeeds."""
        block = BlockFactory(user=self.user, page=self.page, content="TODO ship")
        reminder = Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
            status=Reminder.STATUS_FAILED,
            last_error="previous boom",
        )

        with patch("knowledge.commands.send_due_reminders_command.post_webhook", _ok):
            result = self._run()

        reminder.refresh_from_db()
        self.assertEqual(result["sent"], 1)
        self.assertEqual(reminder.status, Reminder.STATUS_SENT)
        self.assertEqual(reminder.last_error, "")
        self.assertIsNotNone(reminder.sent_at)

    def test_prepends_mention_when_discord_user_id_set(self):
        """When the user has a Discord user ID, the message should start with
        a `<@ID>` mention so Discord actually pings them on delivery."""
        user_with_id = UserFactory(
            discord_webhook_url="https://discord.com/api/webhooks/2/xyz",
            discord_user_id="123456789012345678",
        )
        block = BlockFactory(
            user=user_with_id,
            page=PageFactory(user=user_with_id),
            content="TODO ship",
        )
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        captured: dict = {}

        def _capture(url: str, content: str, **_kwargs):
            captured["url"] = url
            captured["content"] = content
            return DiscordDeliveryResult(True, "")

        with patch(
            "knowledge.commands.send_due_reminders_command.post_webhook", _capture
        ):
            self._run()

        self.assertTrue(captured["content"].startswith("<@123456789012345678> "))
        self.assertIn("TODO ship", captured["content"])

    def test_no_mention_when_discord_user_id_blank(self):
        block = BlockFactory(user=self.user, page=self.page, content="TODO ship")
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        captured: dict = {}

        def _capture(url: str, content: str, **_kwargs):
            captured["content"] = content
            return DiscordDeliveryResult(True, "")

        with patch(
            "knowledge.commands.send_due_reminders_command.post_webhook", _capture
        ):
            self._run()

        self.assertFalse(captured["content"].startswith("<@"))

    def test_prepends_env_label_when_not_prod(self):
        """Non-prod ENVIRONMENT values get an `[<env>] ` label so the user
        can tell which deploy a reminder came from."""
        block = BlockFactory(user=self.user, page=self.page, content="TODO ship")
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        captured: dict = {}

        def _capture(url: str, content: str, **_kwargs):
            captured["content"] = content
            return DiscordDeliveryResult(True, "")

        with patch.dict(os.environ, {"ENVIRONMENT": "staging"}):
            with patch(
                "knowledge.commands.send_due_reminders_command.post_webhook",
                _capture,
            ):
                self._run()

        self.assertTrue(captured["content"].startswith("[staging] "))
        self.assertIn("TODO ship", captured["content"])

    def test_no_env_label_for_prod(self):
        block = BlockFactory(user=self.user, page=self.page, content="TODO ship")
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        captured: dict = {}

        def _capture(url: str, content: str, **_kwargs):
            captured["content"] = content
            return DiscordDeliveryResult(True, "")

        # Class-level patch already pins ENVIRONMENT=prod; just confirm it.
        with patch(
            "knowledge.commands.send_due_reminders_command.post_webhook", _capture
        ):
            self._run()

        self.assertFalse(captured["content"].startswith("["))

    def test_marks_failed_when_user_has_no_webhook(self):
        user_no_webhook = UserFactory(discord_webhook_url="")
        block = BlockFactory(
            user=user_no_webhook,
            page=PageFactory(user=user_no_webhook),
            content="TODO ship",
        )
        reminder = Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        # No patching — the real post_webhook will be called and should
        # short-circuit to "no webhook url configured".
        result = self._run()

        reminder.refresh_from_db()
        self.assertEqual(result["failed"], 1)
        self.assertEqual(reminder.status, Reminder.STATUS_FAILED)
        self.assertIn("no webhook", reminder.last_error.lower())

    def test_appends_page_link_when_site_url_set(self):
        page = PageFactory(user=self.user, title="Backlog", slug="backlog")
        block = BlockFactory(user=self.user, page=page, content="TODO ship")
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        captured: dict = {}

        def _capture(url: str, content: str, **_kwargs):
            captured["content"] = content
            return DiscordDeliveryResult(True, "")

        with (
            self.settings(SITE_URL="https://app.example.com"),
            patch(
                "knowledge.commands.send_due_reminders_command.post_webhook", _capture
            ),
        ):
            self._run()

        self.assertIn(
            "https://app.example.com/knowledge/page/backlog/", captured["content"]
        )

    def test_omits_page_link_when_site_url_is_placeholder(self):
        # Default SITE_URL is "0.0.0.0" with no scheme — produces a broken
        # link, so the formatter should leave it out.
        block = BlockFactory(user=self.user, page=self.page, content="TODO ship")
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        captured: dict = {}

        def _capture(url: str, content: str, **_kwargs):
            captured["content"] = content
            return DiscordDeliveryResult(True, "")

        with (
            self.settings(SITE_URL="0.0.0.0"),
            patch(
                "knowledge.commands.send_due_reminders_command.post_webhook", _capture
            ),
        ):
            self._run()

        self.assertNotIn("/knowledge/page/", captured["content"])
