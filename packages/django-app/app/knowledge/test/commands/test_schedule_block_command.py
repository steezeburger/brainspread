from datetime import date, datetime, time, timedelta

import pytz
from django.test import TestCase
from django.utils import timezone

from knowledge.commands import ScheduleBlockCommand
from knowledge.forms import ScheduleBlockForm
from knowledge.models import Reminder

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestScheduleBlockCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(timezone="America/New_York")
        cls.page = PageFactory(user=cls.user)

    def _run(self, **kwargs):
        form = ScheduleBlockForm({"user": self.user.id, **kwargs})
        self.assertTrue(form.is_valid(), form.errors)
        return ScheduleBlockCommand(form).execute()

    def _to_utc(self, d: date, t: time) -> datetime:
        return (
            pytz.timezone("America/New_York")
            .localize(datetime.combine(d, t))
            .astimezone(pytz.UTC)
        )

    def test_sets_due_date_on_block(self):
        block = BlockFactory(user=self.user, page=self.page)
        target = date(2026, 4, 30)
        result = self._run(block=str(block.uuid), due_date=target)
        # All-day due: stored at user-local midnight, no time component.
        self.assertEqual(result.due_at, self._to_utc(target, time.min))
        self.assertFalse(result.due_at_has_time)
        self.assertEqual(result._due_local_date(), "2026-04-30")
        self.assertIsNone(result._due_local_time())

    def test_sets_timed_due(self):
        block = BlockFactory(user=self.user, page=self.page)
        target = date(2026, 4, 30)
        result = self._run(
            block=str(block.uuid), due_date=target, due_time=time(hour=15)
        )
        self.assertTrue(result.due_at_has_time)
        self.assertEqual(result.due_at, self._to_utc(target, time(hour=15)))
        self.assertEqual(result._due_local_date(), "2026-04-30")
        self.assertEqual(result._due_local_time(), "15:00")

    def test_clears_due_when_empty(self):
        block = BlockFactory(
            user=self.user,
            page=self.page,
            due_at=self._to_utc(date(2026, 4, 30), time.min),
        )
        result = self._run(block=str(block.uuid), due_date="")
        self.assertIsNone(result.due_at)
        self.assertFalse(result.due_at_has_time)

    def test_clear_also_deletes_pending_reminder(self):
        block = BlockFactory(
            user=self.user,
            page=self.page,
            due_at=self._to_utc(date(2026, 4, 30), time.min),
        )
        Reminder.objects.create(
            block=block, fire_at=timezone.now() + timedelta(hours=1)
        )

        self._run(block=str(block.uuid), due_date="")

        self.assertEqual(Reminder.objects.filter(block=block).count(), 0)

    def test_creates_reminder_at_user_chosen_time(self):
        block = BlockFactory(user=self.user, page=self.page)
        target = date(2026, 4, 30)
        chosen_time = time(hour=17, minute=30)

        self._run(
            block=str(block.uuid),
            due_date=target,
            reminder_time=chosen_time,
        )

        reminders = Reminder.objects.filter(block=block)
        self.assertEqual(reminders.count(), 1)
        self.assertEqual(reminders.first().fire_at, self._to_utc(target, chosen_time))

    def test_no_reminder_when_time_not_set(self):
        block = BlockFactory(user=self.user, page=self.page)
        self._run(block=str(block.uuid), due_date=date(2026, 4, 30))
        self.assertEqual(Reminder.objects.filter(block=block).count(), 0)

    def test_reschedule_replaces_pending_reminder(self):
        """Re-saving with a different time leaves a single reminder, not two."""
        block = BlockFactory(user=self.user, page=self.page)

        self._run(
            block=str(block.uuid),
            due_date=date(2026, 4, 30),
            reminder_time=time(hour=9),
        )
        self._run(
            block=str(block.uuid),
            due_date=date(2026, 5, 1),
            reminder_time=time(hour=17),
        )

        reminders = Reminder.objects.filter(block=block)
        self.assertEqual(reminders.count(), 1)
        self.assertEqual(
            reminders.first().fire_at,
            self._to_utc(date(2026, 5, 1), time(hour=17)),
        )

    def test_pending_reminder_time_round_trips_through_block_dict(self):
        """The popover re-opens with the previously-set reminder time
        pre-selected. Verifies block.to_dict surfaces it in user-local."""
        block = BlockFactory(user=self.user, page=self.page)
        chosen = time(hour=17, minute=30)
        self._run(
            block=str(block.uuid),
            due_date=date(2026, 4, 30),
            reminder_time=chosen,
        )

        block.refresh_from_db()
        data = block.to_dict()
        self.assertEqual(data["pending_reminder_time"], "17:30")
        self.assertEqual(data["pending_reminder_date"], "2026-04-30")

    def test_pending_reminder_time_is_none_when_no_pending_reminder(self):
        block = BlockFactory(user=self.user, page=self.page)
        self.assertIsNone(block.to_dict()["pending_reminder_time"])
        self.assertIsNone(block.to_dict()["pending_reminder_date"])

    def test_reminder_can_fire_on_date_different_from_due(self):
        """Submitting a reminder_date earlier than due_date should fire the
        reminder on that earlier date — supports "remind me 1 day before
        due", "1 week before", etc."""
        block = BlockFactory(user=self.user, page=self.page)
        due = date(2026, 4, 30)
        remind_on = date(2026, 4, 23)  # 1 week before
        self._run(
            block=str(block.uuid),
            due_date=due,
            reminder_date=remind_on,
            reminder_time=time(hour=9),
        )

        reminders = Reminder.objects.filter(block=block)
        self.assertEqual(reminders.count(), 1)
        self.assertEqual(
            reminders.first().fire_at,
            self._to_utc(remind_on, time(hour=9)),
        )

        block.refresh_from_db()
        data = block.to_dict()
        self.assertEqual(data["pending_reminder_date"], "2026-04-23")

    def test_reminder_date_falls_back_to_due_date_when_omitted(self):
        block = BlockFactory(user=self.user, page=self.page)
        due = date(2026, 4, 30)
        self._run(
            block=str(block.uuid),
            due_date=due,
            reminder_time=time(hour=9),
            # reminder_date omitted intentionally
        )

        reminders = Reminder.objects.filter(block=block)
        self.assertEqual(reminders.count(), 1)
        self.assertEqual(reminders.first().fire_at, self._to_utc(due, time(hour=9)))

    def test_reschedule_preserves_already_sent_reminders(self):
        """Sent reminders are history and must not be deleted on reschedule."""
        block = BlockFactory(user=self.user, page=self.page)
        sent = Reminder.objects.create(
            block=block,
            fire_at=timezone.now() - timedelta(days=1),
            status=Reminder.STATUS_SENT,
            sent_at=timezone.now() - timedelta(days=1),
        )

        self._run(
            block=str(block.uuid),
            due_date=date(2026, 5, 1),
            reminder_time=time(hour=9),
        )

        self.assertTrue(Reminder.objects.filter(pk=sent.pk).exists())
        # plus the new pending one
        self.assertEqual(
            Reminder.objects.filter(block=block, sent_at__isnull=True).count(), 1
        )
