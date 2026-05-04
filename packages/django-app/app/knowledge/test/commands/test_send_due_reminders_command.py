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

    def _capture_payload(self) -> dict:
        """Patch post_webhook to capture (content, embeds) on a single call.

        Returns a dict with `url`, `content`, `embeds` (always a list,
        empty if not passed). Caller wraps the run() in the returned
        patch context manager.
        """
        captured: dict = {"content": "", "embeds": [], "url": ""}

        def _capture(url: str, content: str = "", *, embeds=None, **_kwargs):
            captured["url"] = url
            captured["content"] = content
            captured["embeds"] = list(embeds or [])
            return DiscordDeliveryResult(True, "")

        return captured, patch(
            "knowledge.commands.send_due_reminders_command.post_webhook", _capture
        )

    def test_mention_in_content_when_discord_user_id_set(self):
        """Discord only pings on mentions in the top-level `content` field
        (mentions inside an embed don't notify), so the @mention has to live
        there even though the rest of the message body moved to embeds."""
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

        captured, patcher = self._capture_payload()
        with patcher:
            self._run()

        self.assertEqual(captured["content"], "<@123456789012345678>")

    def test_no_mention_when_discord_user_id_blank(self):
        block = BlockFactory(user=self.user, page=self.page, content="TODO ship")
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        captured, patcher = self._capture_payload()
        with patcher:
            self._run()

        # Empty (no `<@…>`) when no discord user id is configured. The
        # embed still carries the actual reminder body.
        self.assertEqual(captured["content"], "")
        self.assertEqual(len(captured["embeds"]), 1)

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

    def test_embed_title_is_block_content_first_line(self):
        # The title displays the block's first line as plain bold text.
        # No embed `url` is set, so the title isn't itself a hyperlink —
        # the actionable link lives in `description` (see test below).
        block = BlockFactory(user=self.user, page=self.page, content="TODO ship\nmore")
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        captured, patcher = self._capture_payload()
        with patcher:
            self._run()

        embed = captured["embeds"][0]
        self.assertEqual(embed["title"], "TODO ship")
        self.assertNotIn("url", embed)

    def test_embed_description_carries_open_block_link(self):
        # When SITE_URL is real, the embed gets a description with a
        # markdown link to the block — that's the "open block" call to
        # action that sits visually right under the title.
        page = PageFactory(user=self.user, title="Backlog", slug="backlog")
        block = BlockFactory(user=self.user, page=page, content="TODO ship")
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        captured, patcher = self._capture_payload()
        with self.settings(SITE_URL="https://app.example.com"), patcher:
            self._run()

        embed = captured["embeds"][0]
        expected = (
            f"[Open block →](https://app.example.com/knowledge/page/backlog/"
            f"#block-{block.uuid})"
        )
        self.assertEqual(embed["description"], expected)

    def test_embed_omits_description_when_site_url_is_placeholder(self):
        # Default SITE_URL is "0.0.0.0" — no scheme, can't form a real
        # link, so the embed is rendered without a description.
        block = BlockFactory(user=self.user, page=self.page, content="TODO ship")
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        captured, patcher = self._capture_payload()
        with self.settings(SITE_URL="0.0.0.0"), patcher:
            self._run()

        embed = captured["embeds"][0]
        self.assertNotIn("description", embed)

    def test_due_date_renders_as_inline_field(self):
        scheduled = timezone.now().date() - timedelta(days=1)
        block = BlockFactory(
            user=self.user,
            page=self.page,
            content="TODO ship",
            scheduled_for=scheduled,
        )
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        captured, patcher = self._capture_payload()
        with patcher:
            self._run()

        embed = captured["embeds"][0]
        self.assertEqual(
            embed["fields"],
            [{"name": "Due", "value": scheduled.isoformat(), "inline": True}],
        )

    def test_no_due_field_when_block_unscheduled(self):
        block = BlockFactory(user=self.user, page=self.page, content="TODO ship")
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        captured, patcher = self._capture_payload()
        with patcher:
            self._run()

        embed = captured["embeds"][0]
        self.assertNotIn("fields", embed)

    def test_author_block_carries_env_and_pr_when_set(self):
        # Per-PR staging deploys plumb STAGING_PR_NUMBER + STAGING_PR_URL
        # into the env; the embed surfaces them in the author line so
        # reminders from different per-PR staging envs can be told apart
        # at a glance, and the PR URL is one tap away.
        block = BlockFactory(user=self.user, page=self.page, content="TODO ship")
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        captured, patcher = self._capture_payload()
        with (
            patch.dict(
                os.environ,
                {
                    "ENVIRONMENT": "staging",
                    "STAGING_PR_NUMBER": "114",
                    "STAGING_PR_URL": "https://github.com/x/y/pull/114",
                },
            ),
            patcher,
        ):
            self._run()

        embed = captured["embeds"][0]
        self.assertEqual(
            embed["author"],
            {
                "name": "staging · PR #114",
                "url": "https://github.com/x/y/pull/114",
            },
        )

    def test_author_block_omitted_in_prod(self):
        # Prod has no env tag (the label "prod" adds no signal) and
        # STAGING_PR_* aren't set — embed renders without an author.
        block = BlockFactory(user=self.user, page=self.page, content="TODO ship")
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        captured, patcher = self._capture_payload()
        with patcher:
            # class-level patch already pins ENVIRONMENT=prod
            self._run()

        embed = captured["embeds"][0]
        self.assertNotIn("author", embed)

    def test_footer_carries_page_title(self):
        # Footer gives the user context on which page the block lives in,
        # rendered in small grey text at the bottom of the embed.
        page = PageFactory(user=self.user, title="Backlog", slug="backlog")
        block = BlockFactory(user=self.user, page=page, content="TODO ship")
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        captured, patcher = self._capture_payload()
        with patcher:
            self._run()

        embed = captured["embeds"][0]
        self.assertEqual(embed["footer"], {"text": "on Backlog"})

    def test_color_varies_by_env(self):
        # Quick visual cue for which deploy a ping came from. Asserts on
        # the actual decimal ints we send to Discord.
        block = BlockFactory(user=self.user, page=self.page, content="TODO ship")
        Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(minutes=1),
        )

        cases = [
            ("prod", 0x6366F1),
            ("staging", 0xF59E0B),
            ("local", 0x6B7280),
            ("", 0x6B7280),
        ]
        for env, expected_color in cases:
            with self.subTest(env=env):
                # Reset reminder so it fires again on each iteration.
                Reminder.objects.filter(block=block).update(
                    sent_at=None, status=Reminder.STATUS_PENDING
                )

                captured, patcher = self._capture_payload()
                with patch.dict(os.environ, {"ENVIRONMENT": env}), patcher:
                    self._run()

                embed = captured["embeds"][0]
                self.assertEqual(embed["color"], expected_color)
