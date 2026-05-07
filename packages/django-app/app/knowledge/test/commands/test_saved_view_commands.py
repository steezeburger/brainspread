"""End-to-end tests for the SavedView read commands.

The query engine itself is exercised in test/services/test_query_engine.py.
This file pins the read-side command behaviors (List / Get / Run) that
wrap it. Write-side commands (Create/Update/Delete/Duplicate) ship in a
follow-up commit on this branch and add their own test classes here.
"""

from datetime import date, datetime
from unittest.mock import patch

import pytz
from django.core.exceptions import ValidationError
from django.test import TestCase

from knowledge.commands import (
    GetSavedViewCommand,
    ListSavedViewsCommand,
    RunSavedViewCommand,
)
from knowledge.forms import (
    GetSavedViewForm,
    ListSavedViewsForm,
    RunSavedViewForm,
)
from knowledge.models import SYSTEM_VIEW_OVERDUE, SavedView
from knowledge.services.system_views import seed_system_views_for_user

from ..helpers import BlockFactory, PageFactory, UserFactory


def _utc_noon(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=pytz.UTC)


class _SavedViewTestBase(TestCase):
    today = date(2026, 4, 24)

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(timezone="UTC")
        cls.page = PageFactory(user=cls.user, page_type="page", title="Notes")

    def setUp(self):
        super().setUp()
        patcher = patch("core.models.user.timezone")
        self.mock_tz = patcher.start()
        self.mock_tz.now.return_value = _utc_noon(self.today)
        self.addCleanup(patcher.stop)
        # Tests run on a per-test transaction, so seed system views fresh.
        seed_system_views_for_user(self.user)


class RunSavedViewTests(_SavedViewTestBase):
    def test_run_overdue_returns_overdue_blocks(self):
        # Open todo scheduled yesterday — should match the overdue view.
        match = BlockFactory(
            user=self.user,
            page=self.page,
            block_type="todo",
            scheduled_for=date(2026, 4, 23),
        )
        # Already-done — should not match
        BlockFactory(
            user=self.user,
            page=self.page,
            block_type="done",
            scheduled_for=date(2026, 4, 23),
            completed_at=_utc_noon(self.today),
        )

        form = RunSavedViewForm(
            {"user": self.user.id, "view_slug": SYSTEM_VIEW_OVERDUE}
        )
        self.assertTrue(form.is_valid(), form.errors)
        result = RunSavedViewCommand(form).execute()

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["uuid"], str(match.uuid))
        self.assertFalse(result["truncated"])

    def test_run_truncates_and_flags(self):
        for _ in range(3):
            BlockFactory(
                user=self.user,
                page=self.page,
                block_type="todo",
                scheduled_for=date(2026, 4, 23),
            )
        form = RunSavedViewForm(
            {
                "user": self.user.id,
                "view_slug": SYSTEM_VIEW_OVERDUE,
                "limit": 2,
            }
        )
        self.assertTrue(form.is_valid())
        result = RunSavedViewCommand(form).execute()
        self.assertEqual(result["count"], 2)
        self.assertTrue(result["truncated"])

    def test_run_unknown_view_404(self):
        form = RunSavedViewForm({"user": self.user.id, "view_slug": "does-not-exist"})
        self.assertTrue(form.is_valid())
        with self.assertRaises(ValidationError):
            RunSavedViewCommand(form).execute()


class ListGetSavedViewTests(_SavedViewTestBase):
    def test_list_returns_system_views_first(self):
        # Make a user view to verify ordering.
        SavedView.objects.create(
            user=self.user, name="Z User View", slug="z", filter={}
        )
        form = ListSavedViewsForm({"user": self.user.id})
        self.assertTrue(form.is_valid())
        views = ListSavedViewsCommand(form).execute()
        # System views first (is_system DESC) then by name.
        self.assertTrue(views[0].is_system)

    def test_get_by_slug(self):
        form = GetSavedViewForm(
            {"user": self.user.id, "view_slug": SYSTEM_VIEW_OVERDUE}
        )
        self.assertTrue(form.is_valid(), form.errors)
        view = GetSavedViewCommand(form).execute()
        self.assertEqual(view.slug, SYSTEM_VIEW_OVERDUE)
        self.assertTrue(view.is_system)

    def test_get_requires_uuid_or_slug(self):
        form = GetSavedViewForm({"user": self.user.id})
        self.assertFalse(form.is_valid())
