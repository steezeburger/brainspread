from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from knowledge.models import Reminder, ReminderAction
from knowledge.test.helpers import BlockFactory, PageFactory, UserFactory


class ReminderActionViewTests(TestCase):
    """Public, no-auth view that consumes a reminder-action token from
    the user's Discord notification.

    Tests focus on the HTTP shape — status codes and end-to-end side
    effects on the underlying block/reminder. The command-level matrix
    (snooze, expiry, etc.) lives in
    `test_consume_reminder_action_command.py`.
    """

    def setUp(self) -> None:
        self.user = UserFactory()
        self.page = PageFactory(user=self.user, slug="backlog")
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

    def test_complete_runs_action_and_returns_200(self) -> None:
        action = self._make_action(ReminderAction.ACTION_COMPLETE)
        url = reverse("knowledge:reminder_action", args=[action.token])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.block.refresh_from_db()
        self.assertEqual(self.block.block_type, "done")
        action.refresh_from_db()
        self.assertIsNotNone(action.used_at)

    def test_unknown_token_returns_404(self) -> None:
        url = reverse("knowledge:reminder_action", args=["nope"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_expired_token_returns_410(self) -> None:
        action = self._make_action(
            ReminderAction.ACTION_COMPLETE, expires_in=timedelta(seconds=-1)
        )
        url = reverse("knowledge:reminder_action", args=[action.token])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 410)
        self.block.refresh_from_db()
        self.assertEqual(self.block.block_type, "todo")

    def test_used_token_returns_410_and_does_not_re_run(self) -> None:
        action = self._make_action(ReminderAction.ACTION_COMPLETE)
        action.used_at = timezone.now() - timedelta(minutes=1)
        action.save(update_fields=["used_at", "modified_at"])
        url = reverse("knowledge:reminder_action", args=[action.token])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 410)
        self.block.refresh_from_db()
        self.assertEqual(self.block.block_type, "todo")

    def test_view_does_not_require_authentication(self) -> None:
        # Discord users follow these links unauthenticated. The token
        # itself is the credential — no session/cookie/header should be
        # needed to consume it.
        action = self._make_action(ReminderAction.ACTION_SNOOZE_1H)
        url = reverse("knowledge:reminder_action", args=[action.token])

        # No login_required calls; just hit it raw.
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.reminder.refresh_from_db()
        self.assertEqual(self.reminder.status, Reminder.STATUS_PENDING)
