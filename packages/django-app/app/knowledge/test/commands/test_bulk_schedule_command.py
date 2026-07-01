from datetime import date, time, timedelta

from django.test import TestCase
from django.utils import timezone

from knowledge.commands import BulkScheduleCommand
from knowledge.forms import BulkScheduleForm
from knowledge.models import Reminder

from ..helpers import BlockFactory, PageFactory, UserFactory, due_dt


class TestBulkScheduleCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(timezone="America/New_York")
        cls.page = PageFactory(user=cls.user)

    def _run(self, **kwargs):
        form = BulkScheduleForm({"user": self.user.id, **kwargs})
        self.assertTrue(form.is_valid(), form.errors)
        return BulkScheduleCommand(form).execute()

    def test_date_only_sets_due_on_all_blocks(self):
        b1 = BlockFactory(user=self.user, page=self.page)
        b2 = BlockFactory(user=self.user, page=self.page)
        new_date = date(2026, 4, 30)

        result = self._run(block_uuids=[str(b1.uuid), str(b2.uuid)], new_date=new_date)

        self.assertEqual(result["updated_count"], 2)
        self.assertFalse(result["reminder_set"])
        self.assertEqual(result["missing"], [])
        b1.refresh_from_db()
        b2.refresh_from_db()
        self.assertEqual(b1._due_local_date(), new_date.isoformat())
        self.assertEqual(b2._due_local_date(), new_date.isoformat())
        self.assertFalse(b1.due_at_has_time)
        # No reminder times supplied -> no reminders created.
        self.assertEqual(Reminder.objects.filter(block__in=[b1, b2]).count(), 0)

    def test_date_only_shifts_existing_pending_reminder_by_delta(self):
        old_date = date(2026, 4, 10)
        block = BlockFactory(
            user=self.user,
            page=self.page,
            due_at=due_dt(old_date, tz="America/New_York"),
        )
        fire_at = timezone.now() + timedelta(hours=2)
        reminder = Reminder.objects.create(block=block, fire_at=fire_at)

        new_date = date(2026, 4, 15)  # +5 days
        result = self._run(block_uuids=[str(block.uuid)], new_date=new_date)

        self.assertEqual(result["updated_count"], 1)
        block.refresh_from_db()
        self.assertEqual(block._due_local_date(), new_date.isoformat())
        # Time-of-day preserved: the pending reminder shifts by the same delta.
        reminder.refresh_from_db()
        self.assertEqual(reminder.fire_at, fire_at + timedelta(days=5))

    def test_reminder_mode_creates_a_pending_reminder_on_each_block(self):
        b1 = BlockFactory(user=self.user, page=self.page)
        b2 = BlockFactory(user=self.user, page=self.page)
        new_date = date(2026, 4, 30)

        result = self._run(
            block_uuids=[str(b1.uuid), str(b2.uuid)],
            new_date=new_date,
            reminder_time=time(hour=9),
        )

        self.assertEqual(result["updated_count"], 2)
        self.assertTrue(result["reminder_set"])
        for block in (b1, b2):
            self.assertEqual(
                Reminder.objects.filter(block=block, sent_at__isnull=True).count(),
                1,
            )

    def test_reminders_list_creates_the_set_on_each_block(self):
        b1 = BlockFactory(user=self.user, page=self.page)
        b2 = BlockFactory(user=self.user, page=self.page)
        new_date = date(2026, 4, 30)

        result = self._run(
            block_uuids=[str(b1.uuid), str(b2.uuid)],
            new_date=new_date,
            reminders=[
                {"time": "09:00"},
                {"date": "2026-04-29", "time": "17:00"},
            ],
        )

        self.assertEqual(result["updated_count"], 2)
        self.assertTrue(result["reminder_set"])
        self.assertEqual(result["reminders_count"], 2)
        for block in (b1, b2):
            self.assertEqual(
                Reminder.objects.filter(block=block, sent_at__isnull=True).count(),
                2,
            )

    def test_date_only_shifts_every_pending_reminder(self):
        old_date = date(2026, 4, 10)
        block = BlockFactory(
            user=self.user,
            page=self.page,
            due_at=due_dt(old_date, tz="America/New_York"),
        )
        fire_1 = timezone.now() + timedelta(hours=2)
        fire_2 = timezone.now() + timedelta(hours=5)
        r1 = Reminder.objects.create(block=block, fire_at=fire_1)
        r2 = Reminder.objects.create(block=block, fire_at=fire_2)

        self._run(block_uuids=[str(block.uuid)], new_date=date(2026, 4, 15))

        r1.refresh_from_db()
        r2.refresh_from_db()
        self.assertEqual(r1.fire_at, fire_1 + timedelta(days=5))
        self.assertEqual(r2.fire_at, fire_2 + timedelta(days=5))

    def test_skips_blocks_owned_by_another_user(self):
        mine = BlockFactory(user=self.user, page=self.page)
        other = UserFactory()
        other_page = PageFactory(user=other, slug="other-bulk-schedule")
        theirs = BlockFactory(user=other, page=other_page)
        new_date = date(2026, 4, 30)

        result = self._run(
            block_uuids=[str(mine.uuid), str(theirs.uuid)], new_date=new_date
        )

        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(result["missing"], [str(theirs.uuid)])
        theirs.refresh_from_db()
        self.assertIsNone(theirs.due_at)

    def test_rejects_empty_block_uuids(self):
        form = BulkScheduleForm(
            {"user": self.user.id, "block_uuids": [], "new_date": date(2026, 4, 30)}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("block_uuids", form.errors)
