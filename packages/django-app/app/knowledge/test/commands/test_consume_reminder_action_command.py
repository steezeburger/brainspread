from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from knowledge.commands import ConsumeReminderActionCommand
from knowledge.forms import ConsumeReminderActionForm
from knowledge.models import Reminder, ReminderAction

from ..helpers import BlockFactory, PageFactory, UserFactory


class ConsumeReminderActionCommandTests(TestCase):
    def setUp(self) -> None:
        self.user = UserFactory()
        self.page = PageFactory(user=self.user)
        self.block = BlockFactory(
            user=self.user,
            page=self.page,
            content="TODO ship",
            block_type="todo",
        )
        self.reminder = Reminder.objects.create(
            block=self.block,
            fire_at=timezone.now() - timedelta(minutes=5),
            status=Reminder.STATUS_SENT,
            sent_at=timezone.now() - timedelta(minutes=4),
        )

    def _make_action(self, action: str, *, expires_in=timedelta(days=7)):
        return ReminderAction.objects.create(
            reminder=self.reminder,
            action=action,
            expires_at=timezone.now() + expires_in,
        )

    def _run(self, token: str, *, now=None):
        data = {"token": token}
        if now is not None:
            data["now"] = now.isoformat()
        form = ConsumeReminderActionForm(data)
        assert form.is_valid(), form.errors
        return ConsumeReminderActionCommand(form).execute()

    def test_complete_marks_block_done_and_consumes_token(self) -> None:
        action = self._make_action(ReminderAction.ACTION_COMPLETE)

        result = self._run(action.token)

        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["action"], ReminderAction.ACTION_COMPLETE)
        self.assertEqual(result["block_uuid"], str(self.block.uuid))
        self.assertEqual(result["page_slug"], self.page.slug)

        self.block.refresh_from_db()
        self.assertEqual(self.block.block_type, "done")
        self.assertIsNotNone(self.block.completed_at)

        action.refresh_from_db()
        self.assertIsNotNone(action.used_at)

    def test_snooze_1h_resets_pending_with_new_fire_at(self) -> None:
        action = self._make_action(ReminderAction.ACTION_SNOOZE_1H)
        pinned = timezone.now()

        result = self._run(action.token, now=pinned)

        self.assertEqual(result["status"], "executed")

        self.reminder.refresh_from_db()
        self.assertEqual(self.reminder.status, Reminder.STATUS_PENDING)
        self.assertIsNone(self.reminder.sent_at)
        self.assertEqual(
            self.reminder.fire_at.replace(microsecond=0),
            (pinned + timedelta(hours=1)).replace(microsecond=0),
        )

        action.refresh_from_db()
        self.assertIsNotNone(action.used_at)

    def test_snooze_1d_resets_pending_with_new_fire_at(self) -> None:
        action = self._make_action(ReminderAction.ACTION_SNOOZE_1D)
        pinned = timezone.now()

        result = self._run(action.token, now=pinned)

        self.assertEqual(result["status"], "executed")

        self.reminder.refresh_from_db()
        self.assertEqual(self.reminder.status, Reminder.STATUS_PENDING)
        self.assertEqual(
            self.reminder.fire_at.replace(microsecond=0),
            (pinned + timedelta(days=1)).replace(microsecond=0),
        )

    def test_unknown_token_returns_not_found(self) -> None:
        result = self._run("definitely-not-a-real-token-value")
        self.assertEqual(result["status"], "not_found")
        self.assertIsNone(result["block_uuid"])

    def test_expired_token_is_rejected_and_block_unchanged(self) -> None:
        action = self._make_action(
            ReminderAction.ACTION_COMPLETE, expires_in=timedelta(seconds=-1)
        )

        result = self._run(action.token)

        self.assertEqual(result["status"], "expired")
        self.block.refresh_from_db()
        self.assertEqual(self.block.block_type, "todo")
        action.refresh_from_db()
        self.assertIsNone(action.used_at)

    def test_already_used_token_does_not_re_run(self) -> None:
        action = self._make_action(ReminderAction.ACTION_COMPLETE)
        action.used_at = timezone.now() - timedelta(minutes=1)
        action.save(update_fields=["used_at", "modified_at"])

        result = self._run(action.token)

        self.assertEqual(result["status"], "already_used")
        self.block.refresh_from_db()
        self.assertEqual(self.block.block_type, "todo")

    def test_completed_block_is_no_op_and_marks_token_used(self) -> None:
        # If the user clicks an action after completing the block via
        # another channel, we treat it as a graceful no-op rather than
        # un-completing or re-snoozing — see the command docstring.
        self.block.block_type = "done"
        self.block.completed_at = timezone.now()
        self.block.save(update_fields=["block_type", "completed_at", "modified_at"])

        action = self._make_action(ReminderAction.ACTION_SNOOZE_1H)

        result = self._run(action.token)

        self.assertEqual(result["status"], "block_completed")
        self.assertEqual(result["block_uuid"], str(self.block.uuid))

        action.refresh_from_db()
        self.assertIsNotNone(action.used_at)

        self.reminder.refresh_from_db()
        # No snooze applied — reminder still has its original sent state.
        self.assertEqual(self.reminder.status, Reminder.STATUS_SENT)
