from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from knowledge.commands import ConsumeReminderActionCommand
from knowledge.forms import ConsumeReminderActionForm
from knowledge.models import Reminder, ReminderAction
from knowledge.repositories.page_repository import PageRepository

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

    def test_snooze_15m_resets_pending_with_new_fire_at(self) -> None:
        action = self._make_action(ReminderAction.ACTION_SNOOZE_15M)
        pinned = timezone.now()

        result = self._run(action.token, now=pinned)

        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["detail"], "Snoozed for 15 minutes.")

        self.reminder.refresh_from_db()
        self.assertEqual(self.reminder.status, Reminder.STATUS_PENDING)
        self.assertIsNone(self.reminder.sent_at)
        self.assertEqual(
            self.reminder.fire_at.replace(microsecond=0),
            (pinned + timedelta(minutes=15)).replace(microsecond=0),
        )

    def test_snooze_30m_resets_pending_with_new_fire_at(self) -> None:
        action = self._make_action(ReminderAction.ACTION_SNOOZE_30M)
        pinned = timezone.now()

        result = self._run(action.token, now=pinned)

        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["detail"], "Snoozed for 30 minutes.")

        self.reminder.refresh_from_db()
        self.assertEqual(
            self.reminder.fire_at.replace(microsecond=0),
            (pinned + timedelta(minutes=30)).replace(microsecond=0),
        )

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

    def test_mark_doing_flips_block_to_doing_and_consumes_token(self) -> None:
        # The block starts as "todo"; clicking Mark doing should land
        # it in the "doing" state with the content prefix swapped and
        # the token marked used. The reminder itself is left alone —
        # marking doing isn't a deferral, the same reminder may fire
        # follow-ups or the user may want to mark done later.
        action = self._make_action(ReminderAction.ACTION_MARK_DOING)

        result = self._run(action.token)

        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["action"], ReminderAction.ACTION_MARK_DOING)
        self.assertEqual(result["detail"], "Marked the block as doing.")
        self.assertEqual(result["block_uuid"], str(self.block.uuid))

        self.block.refresh_from_db()
        self.assertEqual(self.block.block_type, "doing")
        # "Mark doing" is not a terminal state — completed_at stays
        # empty so the in-app pending-reminder lookup keeps working.
        self.assertIsNone(self.block.completed_at)
        # SetBlockTypeCommand swaps the leading "TODO" prefix to "DOING".
        self.assertTrue(self.block.content.startswith("DOING"))

        action.refresh_from_db()
        self.assertIsNotNone(action.used_at)

        self.reminder.refresh_from_db()
        # Reminder is untouched — its sent state from setUp persists.
        self.assertEqual(self.reminder.status, Reminder.STATUS_SENT)

    def test_mark_doing_on_already_doing_block_is_idempotent(self) -> None:
        # If the user clicks "Mark doing" twice (different tokens) or
        # the block was already moved to doing in another channel,
        # the second consume just marks the token used.
        self.block.block_type = "doing"
        self.block.content = "DOING ship"
        self.block.save(update_fields=["block_type", "content", "modified_at"])

        action = self._make_action(ReminderAction.ACTION_MARK_DOING)

        result = self._run(action.token)

        self.assertEqual(result["status"], "executed")
        self.block.refresh_from_db()
        self.assertEqual(self.block.block_type, "doing")
        action.refresh_from_db()
        self.assertIsNotNone(action.used_at)

    def test_move_to_today_moves_block_to_daily_and_consumes_token(self) -> None:
        # Clicking "Move to today" relocates the block (and any
        # descendants) onto today's daily note, creating it if needed.
        # The block's task state is untouched — moving is neither
        # completing nor deferring — and the reminder keeps its sent
        # state.
        child = BlockFactory(
            user=self.user,
            page=self.page,
            parent=self.block,
            content="subtask",
        )
        action = self._make_action(ReminderAction.ACTION_MOVE_TO_TODAY)

        result = self._run(action.token)

        today_slug = self.user.today().strftime("%Y-%m-%d")
        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["action"], ReminderAction.ACTION_MOVE_TO_TODAY)
        self.assertEqual(result["detail"], "Moved the block to today's daily note.")
        self.assertEqual(result["block_uuid"], str(self.block.uuid))
        # The confirmation page's "Open block" link should point at the
        # daily note the block just landed on, not the old page.
        self.assertEqual(result["page_slug"], today_slug)

        self.block.refresh_from_db()
        self.assertEqual(self.block.page.slug, today_slug)
        self.assertEqual(self.block.page.page_type, "daily")
        self.assertIsNone(self.block.parent)
        self.assertEqual(self.block.block_type, "todo")

        child.refresh_from_db()
        self.assertEqual(child.page.slug, today_slug)
        self.assertEqual(child.parent_id, self.block.pk)

        action.refresh_from_db()
        self.assertIsNotNone(action.used_at)

        self.reminder.refresh_from_db()
        self.assertEqual(self.reminder.status, Reminder.STATUS_SENT)

    def test_move_to_today_when_already_on_todays_daily_is_idempotent(self) -> None:
        # The send-side check skips minting this action for blocks
        # already on today's daily, but the user can also click a link
        # minted yesterday after midnight rolls the daily over — the
        # move command treats already-there as a graceful no-op and the
        # token still burns.
        today = self.user.today()
        daily, _ = PageRepository.get_or_create_daily_note(self.user, today)
        self.block.page = daily
        self.block.save(update_fields=["page", "modified_at"])

        action = self._make_action(ReminderAction.ACTION_MOVE_TO_TODAY)

        result = self._run(action.token)

        self.assertEqual(result["status"], "executed")
        self.block.refresh_from_db()
        self.assertEqual(self.block.page_id, daily.pk)
        action.refresh_from_db()
        self.assertIsNotNone(action.used_at)

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
