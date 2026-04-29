from datetime import date, datetime
from unittest.mock import patch

import pytz
from django.test import TestCase
from django.utils import timezone

from knowledge.commands import GetPageWithBlocksCommand
from knowledge.forms import GetPageWithBlocksForm

from ..helpers import BlockFactory, PageFactory, UserFactory


def _utc_noon(d: date) -> datetime:
    """Aware UTC datetime at noon, used to drive core.helpers.timezone.now()
    so today_for_user(user) resolves to the target date."""
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=pytz.UTC)


class TestGetPageWithBlocksOverdue(TestCase):
    """Overdue blocks surface on today's daily page only (issue #59)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def _run(self, **form_kwargs):
        form_data = {"user": self.user.id, **form_kwargs}
        form = GetPageWithBlocksForm(form_data)
        self.assertTrue(form.is_valid(), form.errors)
        return GetPageWithBlocksCommand(form).execute()

    @patch("core.helpers.timezone")
    def test_overdue_surfaces_on_todays_daily_page(self, mock_timezone):
        today = date(2026, 4, 24)
        mock_timezone.now.return_value = _utc_noon(today)

        yesterday = date(2026, 4, 23)
        old_page = PageFactory(
            user=self.user,
            date=yesterday,
            page_type="daily",
            title="2026-04-23",
            slug="2026-04-23",
        )
        overdue = BlockFactory(
            user=self.user,
            page=old_page,
            content="TODO overdue",
            block_type="todo",
            scheduled_for=yesterday,
        )

        _, direct_blocks, _, overdue_blocks = self._run(date=today)

        self.assertEqual(len(overdue_blocks), 1)
        self.assertEqual(str(overdue_blocks[0].uuid), str(overdue.uuid))
        self.assertEqual(len(direct_blocks), 0)

    @patch("core.helpers.timezone")
    def test_overdue_empty_on_past_daily_page(self, mock_timezone):
        today = date(2026, 4, 24)
        mock_timezone.now.return_value = _utc_noon(today)

        two_days_ago = date(2026, 4, 22)
        yesterday = date(2026, 4, 23)
        # scheduled for yesterday — would be overdue on today, but we're
        # viewing 2 days ago, not today.
        old_page = PageFactory(
            user=self.user,
            date=yesterday,
            page_type="daily",
            title="2026-04-23",
            slug="2026-04-23",
        )
        BlockFactory(
            user=self.user,
            page=old_page,
            content="TODO overdue",
            block_type="todo",
            scheduled_for=yesterday,
        )

        _, _, _, overdue_blocks = self._run(date=two_days_ago)
        self.assertEqual(overdue_blocks, [])

    @patch("core.helpers.timezone")
    def test_overdue_empty_on_non_daily_page(self, mock_timezone):
        mock_timezone.now.return_value = _utc_noon(date(2026, 4, 24))

        regular_page = PageFactory(
            user=self.user,
            page_type="page",
            title="Project Notes",
            slug="project-notes",
        )
        yesterday = date(2026, 4, 23)
        old_page = PageFactory(
            user=self.user,
            date=yesterday,
            page_type="daily",
            title="2026-04-23",
            slug="2026-04-23",
        )
        BlockFactory(
            user=self.user,
            page=old_page,
            content="TODO overdue",
            block_type="todo",
            scheduled_for=yesterday,
        )

        _, _, _, overdue_blocks = self._run(slug=regular_page.slug)
        self.assertEqual(overdue_blocks, [])

    @patch("core.helpers.timezone")
    def test_overdue_excludes_completed_and_done_block_types(self, mock_timezone):
        today = date(2026, 4, 24)
        mock_timezone.now.return_value = _utc_noon(today)

        yesterday = date(2026, 4, 23)
        old_page = PageFactory(
            user=self.user,
            date=yesterday,
            page_type="daily",
            title="2026-04-23",
            slug="2026-04-23",
        )
        # wontdo — terminal state, excluded from overdue
        BlockFactory(
            user=self.user,
            page=old_page,
            content="WONTDO nope",
            block_type="wontdo",
            scheduled_for=yesterday,
        )
        # done — terminal, excluded
        BlockFactory(
            user=self.user,
            page=old_page,
            content="DONE shipped",
            block_type="done",
            scheduled_for=yesterday,
        )
        # todo but completed_at is set — excluded via completed_at predicate
        BlockFactory(
            user=self.user,
            page=old_page,
            content="TODO finished",
            block_type="todo",
            scheduled_for=yesterday,
            completed_at=timezone.now(),
        )
        # doing — not terminal, included
        included = BlockFactory(
            user=self.user,
            page=old_page,
            content="DOING real one",
            block_type="doing",
            scheduled_for=yesterday,
        )

        _, _, _, overdue_blocks = self._run(date=today)
        self.assertEqual([str(b.uuid) for b in overdue_blocks], [str(included.uuid)])

    @patch("core.helpers.timezone")
    def test_overdue_scoped_to_current_user(self, mock_timezone):
        today = date(2026, 4, 24)
        mock_timezone.now.return_value = _utc_noon(today)

        other_user = UserFactory()
        yesterday = date(2026, 4, 23)
        other_page = PageFactory(
            user=other_user,
            date=yesterday,
            page_type="daily",
            title="2026-04-23",
            slug="other-user-2026-04-23",
        )
        BlockFactory(
            user=other_user,
            page=other_page,
            content="TODO other user's overdue",
            block_type="todo",
            scheduled_for=yesterday,
        )

        _, _, _, overdue_blocks = self._run(date=today)
        self.assertEqual(overdue_blocks, [])
