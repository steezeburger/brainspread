from datetime import date, datetime
from unittest.mock import patch

import pytz
from django.test import TestCase

from knowledge.commands import GetPageWithBlocksCommand
from knowledge.forms import GetPageWithBlocksForm

from ..helpers import BlockFactory, PageFactory, UserFactory, due_dt


def _utc_noon(d: date) -> datetime:
    """Aware UTC datetime at noon, used to drive core.models.user.timezone.now()
    so today_for_user(user) resolves to the target date."""
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=pytz.UTC)


class TestGetPageWithBlocks(TestCase):
    """The unified page-load command returns (page, direct_blocks,
    referenced_blocks, embedded_views). The old fifth element — the
    hard-coded overdue list for today's daily — was removed in favor
    of embedding the system 'overdue' saved view."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def _run(self, **form_kwargs):
        form_data = {"user": self.user.id, **form_kwargs}
        form = GetPageWithBlocksForm(form_data)
        self.assertTrue(form.is_valid(), form.errors)
        return GetPageWithBlocksCommand(form).execute()

    @patch("core.models.user.timezone")
    def test_returns_page_blocks_and_embeds(self, mock_timezone):
        today = date(2026, 4, 24)
        mock_timezone.now.return_value = _utc_noon(today)

        result = self._run(date=today)
        self.assertEqual(len(result), 4)
        page, direct_blocks, referenced_blocks, embedded_views = result
        self.assertEqual(page.page_type, "daily")
        self.assertEqual(direct_blocks, [])
        self.assertEqual(referenced_blocks, [])
        self.assertEqual(embedded_views, [])

    @patch("core.models.user.timezone")
    def test_no_overdue_sidecar_on_todays_daily(self, mock_timezone):
        # An overdue block on an older daily must NOT leak into today's
        # page load anymore — overdue is an embeddable saved view now.
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
            due_at=due_dt(yesterday),
        )

        _, direct_blocks, referenced_blocks, _ = self._run(date=today)
        rendered_uuids = {str(b.uuid) for b in direct_blocks + referenced_blocks}
        self.assertNotIn(str(overdue.uuid), rendered_uuids)
