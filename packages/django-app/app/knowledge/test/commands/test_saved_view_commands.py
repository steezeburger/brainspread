"""End-to-end tests for the SavedView CRUD + run + duplicate commands.

The query engine itself is exercised in test/services/test_query_engine.py.
This file pins the command behaviors that wrap it: validation rules,
system-view read-only enforcement, slug uniqueness, and the run-vs-stored
mapping.
"""

from datetime import date, datetime
from unittest.mock import patch

import pytz
from django.core.exceptions import ValidationError
from django.test import TestCase

from knowledge.commands import (
    CreateSavedViewCommand,
    DeleteSavedViewCommand,
    DuplicateSavedViewCommand,
    GetSavedViewCommand,
    ListSavedViewsCommand,
    RunSavedViewCommand,
    UpdateSavedViewCommand,
)
from knowledge.forms import (
    CreateSavedViewForm,
    DeleteSavedViewForm,
    DuplicateSavedViewForm,
    GetSavedViewForm,
    ListSavedViewsForm,
    RunSavedViewForm,
    UpdateSavedViewForm,
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


class CreateSavedViewTests(_SavedViewTestBase):
    def _make(self, **overrides):
        data = {
            "user": self.user.id,
            "name": "My View",
            "filter": {"block_type": "todo"},
        }
        data.update(overrides)
        form = CreateSavedViewForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        return CreateSavedViewCommand(form).execute()

    def test_creates_with_auto_slug(self):
        view = self._make()
        self.assertEqual(view.slug, "my-view")
        self.assertFalse(view.is_system)

    def test_rejects_duplicate_slug(self):
        self._make(slug="dupe")
        with self.assertRaises(ValidationError):
            self._make(name="Other", slug="dupe")

    def test_rejects_invalid_filter_at_create(self):
        # Compile-time validation should reject unknown predicate fields
        # rather than wait for first run.
        with self.assertRaises(ValidationError):
            self._make(filter={"never_heard_of_it": 1})


class UpdateSavedViewTests(_SavedViewTestBase):
    def _create_user_view(self):
        form = CreateSavedViewForm(
            {
                "user": self.user.id,
                "name": "Editable",
                "filter": {"block_type": "todo"},
            }
        )
        self.assertTrue(form.is_valid())
        return CreateSavedViewCommand(form).execute()

    def test_can_edit_user_view(self):
        view = self._create_user_view()
        form = UpdateSavedViewForm(
            {
                "user": self.user.id,
                "view_uuid": str(view.uuid),
                "name": "Renamed",
                "filter": {"block_type": "doing"},
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        updated = UpdateSavedViewCommand(form).execute()
        self.assertEqual(updated.name, "Renamed")
        self.assertEqual(updated.filter, {"block_type": "doing"})

    def test_cannot_edit_system_view(self):
        sys_view = SavedView.objects.get(
            user=self.user, slug=SYSTEM_VIEW_OVERDUE, is_system=True
        )
        form = UpdateSavedViewForm(
            {
                "user": self.user.id,
                "view_uuid": str(sys_view.uuid),
                "name": "Hijack",
            }
        )
        self.assertTrue(form.is_valid())
        with self.assertRaises(ValidationError):
            UpdateSavedViewCommand(form).execute()


class DeleteSavedViewTests(_SavedViewTestBase):
    def test_delete_user_view(self):
        form = CreateSavedViewForm(
            {
                "user": self.user.id,
                "name": "Tossable",
                "filter": {"block_type": "todo"},
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        view = CreateSavedViewCommand(form).execute()

        del_form = DeleteSavedViewForm(
            {"user": self.user.id, "view_uuid": str(view.uuid)}
        )
        self.assertTrue(del_form.is_valid())
        DeleteSavedViewCommand(del_form).execute()
        self.assertFalse(SavedView.objects.filter(uuid=view.uuid).exists())

    def test_cannot_delete_system_view(self):
        sys_view = SavedView.objects.get(
            user=self.user, slug=SYSTEM_VIEW_OVERDUE, is_system=True
        )
        form = DeleteSavedViewForm(
            {"user": self.user.id, "view_uuid": str(sys_view.uuid)}
        )
        self.assertTrue(form.is_valid())
        with self.assertRaises(ValidationError):
            DeleteSavedViewCommand(form).execute()


class DuplicateSavedViewTests(_SavedViewTestBase):
    def test_duplicates_system_view_into_user_view(self):
        sys_view = SavedView.objects.get(
            user=self.user, slug=SYSTEM_VIEW_OVERDUE, is_system=True
        )
        form = DuplicateSavedViewForm(
            {"user": self.user.id, "view_uuid": str(sys_view.uuid)}
        )
        self.assertTrue(form.is_valid())
        clone = DuplicateSavedViewCommand(form).execute()
        self.assertFalse(clone.is_system)
        self.assertEqual(clone.filter, sys_view.filter)
        self.assertNotEqual(clone.uuid, sys_view.uuid)
        self.assertIn("(copy)", clone.name)

    def test_duplicate_unique_suffix(self):
        first = SavedView.objects.create(
            user=self.user, name="Foo", slug="foo", filter={}
        )
        # First clone → "foo-copy"
        DuplicateSavedViewCommand(
            DuplicateSavedViewForm({"user": self.user.id, "view_uuid": str(first.uuid)})
        ).execute()
        # Second clone of same view → should auto-suffix
        form = DuplicateSavedViewForm(
            {"user": self.user.id, "view_uuid": str(first.uuid)}
        )
        self.assertTrue(form.is_valid())
        second = DuplicateSavedViewCommand(form).execute()
        self.assertNotIn(second.slug, [first.slug, "foo-copy"])


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
