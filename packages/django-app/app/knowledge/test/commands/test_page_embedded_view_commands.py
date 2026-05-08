"""Tests for the PageEmbeddedView CRUD commands.

PageEmbeddedView replaces the earlier ``Block(block_type='query')``
shape — embeds are no longer blocks; they're a small per-page pointer
record. The commands here cover create (idempotent on (page,
saved_view)), delete (404s for cross-user UUIDs), update (partial —
collapsed and/or order), and bulk reorder.
"""

from datetime import date, datetime
from unittest.mock import patch

import pytz
from django.core.exceptions import ValidationError
from django.test import TestCase

from knowledge.commands import (
    CreatePageEmbeddedViewCommand,
    DeletePageEmbeddedViewCommand,
    ReorderPageEmbeddedViewsCommand,
    UpdatePageEmbeddedViewCommand,
)
from knowledge.forms import (
    CreatePageEmbeddedViewForm,
    DeletePageEmbeddedViewForm,
    ReorderPageEmbeddedViewsForm,
    UpdatePageEmbeddedViewForm,
)
from knowledge.models import PageEmbeddedView, SavedView

from ..helpers import PageFactory, UserFactory


def _utc_noon(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=pytz.UTC)


class _EmbedTestBase(TestCase):
    today = date(2026, 4, 24)

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(timezone="UTC")
        cls.other_user = UserFactory(timezone="UTC")
        cls.page = PageFactory(user=cls.user, page_type="page", title="Notes")
        cls.view = SavedView.objects.create(
            user=cls.user, name="Open todos", slug="open-todos", filter={}
        )

    def setUp(self):
        super().setUp()
        patcher = patch("core.models.user.timezone")
        self.mock_tz = patcher.start()
        self.mock_tz.now.return_value = _utc_noon(self.today)
        self.addCleanup(patcher.stop)


class CreateEmbedTests(_EmbedTestBase):
    def _make(self, **overrides):
        data = {
            "user": self.user.id,
            "page_uuid": str(self.page.uuid),
            "saved_view_uuid": str(self.view.uuid),
        }
        data.update(overrides)
        form = CreatePageEmbeddedViewForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        return CreatePageEmbeddedViewCommand(form).execute()

    def test_creates_with_appended_order(self):
        embed = self._make()
        self.assertEqual(embed.order, 0)
        self.assertEqual(embed.page, self.page)
        self.assertEqual(embed.saved_view, self.view)
        # Second create against a different view should slot in at order=1.
        other_view = SavedView.objects.create(
            user=self.user, name="Done this week", slug="done-week", filter={}
        )
        second = self._make(saved_view_uuid=str(other_view.uuid))
        self.assertEqual(second.order, 1)

    def test_idempotent_on_page_and_view(self):
        first = self._make()
        again = self._make()
        self.assertEqual(first.uuid, again.uuid)
        self.assertEqual(PageEmbeddedView.objects.count(), 1)

    def test_rejects_other_users_view(self):
        their_view = SavedView.objects.create(
            user=self.other_user, name="Theirs", slug="theirs", filter={}
        )
        with self.assertRaises(ValidationError):
            self._make(saved_view_uuid=str(their_view.uuid))

    def test_rejects_other_users_page(self):
        their_page = PageFactory(user=self.other_user, page_type="page", title="Theirs")
        with self.assertRaises(ValidationError):
            self._make(page_uuid=str(their_page.uuid))


class DeleteEmbedTests(_EmbedTestBase):
    def test_delete_own_embed(self):
        embed = PageEmbeddedView.objects.create(
            user=self.user, page=self.page, saved_view=self.view
        )
        form = DeletePageEmbeddedViewForm(
            {"user": self.user.id, "embed_uuid": str(embed.uuid)}
        )
        self.assertTrue(form.is_valid(), form.errors)
        DeletePageEmbeddedViewCommand(form).execute()
        self.assertFalse(PageEmbeddedView.objects.filter(uuid=embed.uuid).exists())

    def test_cannot_delete_other_users_embed(self):
        their_page = PageFactory(user=self.other_user, page_type="page", title="Theirs")
        their_view = SavedView.objects.create(
            user=self.other_user, name="X", slug="x", filter={}
        )
        their_embed = PageEmbeddedView.objects.create(
            user=self.other_user, page=their_page, saved_view=their_view
        )
        form = DeletePageEmbeddedViewForm(
            {"user": self.user.id, "embed_uuid": str(their_embed.uuid)}
        )
        self.assertTrue(form.is_valid())
        with self.assertRaises(ValidationError):
            DeletePageEmbeddedViewCommand(form).execute()


class UpdateEmbedTests(_EmbedTestBase):
    def test_toggle_collapsed(self):
        embed = PageEmbeddedView.objects.create(
            user=self.user, page=self.page, saved_view=self.view, collapsed=False
        )
        form = UpdatePageEmbeddedViewForm(
            {
                "user": self.user.id,
                "embed_uuid": str(embed.uuid),
                "collapsed": True,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        updated = UpdatePageEmbeddedViewCommand(form).execute()
        self.assertTrue(updated.collapsed)

    def test_set_order(self):
        embed = PageEmbeddedView.objects.create(
            user=self.user, page=self.page, saved_view=self.view, order=0
        )
        form = UpdatePageEmbeddedViewForm(
            {"user": self.user.id, "embed_uuid": str(embed.uuid), "order": 5}
        )
        self.assertTrue(form.is_valid())
        updated = UpdatePageEmbeddedViewCommand(form).execute()
        self.assertEqual(updated.order, 5)


class ReorderEmbedTests(_EmbedTestBase):
    def _make_embed(self, slug: str, order: int) -> PageEmbeddedView:
        view = SavedView.objects.create(user=self.user, name=slug, slug=slug, filter={})
        return PageEmbeddedView.objects.create(
            user=self.user, page=self.page, saved_view=view, order=order
        )

    def test_reorder_assigns_index(self):
        a = self._make_embed("a", 0)
        b = self._make_embed("b", 1)
        c = self._make_embed("c", 2)

        form = ReorderPageEmbeddedViewsForm(
            {
                "user": self.user.id,
                "page_uuid": str(self.page.uuid),
                "ordered_uuids": [str(c.uuid), str(a.uuid), str(b.uuid)],
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        ReorderPageEmbeddedViewsCommand(form).execute()

        a.refresh_from_db()
        b.refresh_from_db()
        c.refresh_from_db()
        self.assertEqual(c.order, 0)
        self.assertEqual(a.order, 1)
        self.assertEqual(b.order, 2)

    def test_reorder_rejects_other_users_page(self):
        their_page = PageFactory(user=self.other_user, page_type="page", title="Theirs")
        form = ReorderPageEmbeddedViewsForm(
            {
                "user": self.user.id,
                "page_uuid": str(their_page.uuid),
                "ordered_uuids": [],
            }
        )
        self.assertTrue(form.is_valid())
        with self.assertRaises(ValidationError):
            ReorderPageEmbeddedViewsCommand(form).execute()
