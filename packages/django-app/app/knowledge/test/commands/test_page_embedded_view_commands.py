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

    def test_set_color(self):
        embed = PageEmbeddedView.objects.create(
            user=self.user, page=self.page, saved_view=self.view
        )
        form = UpdatePageEmbeddedViewForm(
            {"user": self.user.id, "embed_uuid": str(embed.uuid), "color": "red"}
        )
        self.assertTrue(form.is_valid(), form.errors)
        updated = UpdatePageEmbeddedViewCommand(form).execute()
        self.assertEqual(updated.color, "red")
        self.assertEqual(updated.to_dict()["color"], "red")

    def test_clear_color(self):
        embed = PageEmbeddedView.objects.create(
            user=self.user, page=self.page, saved_view=self.view, color="red"
        )
        form = UpdatePageEmbeddedViewForm(
            {"user": self.user.id, "embed_uuid": str(embed.uuid), "color": ""}
        )
        self.assertTrue(form.is_valid(), form.errors)
        updated = UpdatePageEmbeddedViewCommand(form).execute()
        self.assertEqual(updated.color, "")

    def test_update_without_color_leaves_it_unchanged(self):
        embed = PageEmbeddedView.objects.create(
            user=self.user, page=self.page, saved_view=self.view, color="blue"
        )
        form = UpdatePageEmbeddedViewForm(
            {"user": self.user.id, "embed_uuid": str(embed.uuid), "collapsed": True}
        )
        self.assertTrue(form.is_valid(), form.errors)
        updated = UpdatePageEmbeddedViewCommand(form).execute()
        self.assertEqual(updated.color, "blue")
        self.assertTrue(updated.collapsed)

    def test_rejects_unknown_color(self):
        embed = PageEmbeddedView.objects.create(
            user=self.user, page=self.page, saved_view=self.view
        )
        form = UpdatePageEmbeddedViewForm(
            {"user": self.user.id, "embed_uuid": str(embed.uuid), "color": "magenta"}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("color", form.errors)


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


class DailyScopeTests(_EmbedTestBase):
    """Embeds created on a daily page are stored daily-scoped so they
    render on whichever daily page the user opens, not just the one
    they happened to be on when they clicked Embed.
    """

    def _make_daily(self, d: date):
        return PageFactory(
            user=self.user,
            page_type="daily",
            date=d,
            title=d.isoformat(),
            slug=d.isoformat(),
        )

    def _make_embed(self, page, view):
        form = CreatePageEmbeddedViewForm(
            {
                "user": self.user.id,
                "page_uuid": str(page.uuid),
                "saved_view_uuid": str(view.uuid),
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        return CreatePageEmbeddedViewCommand(form).execute()

    def test_embed_on_daily_is_daily_scoped_with_null_page(self):
        yesterday = self._make_daily(date(2026, 4, 23))
        embed = self._make_embed(yesterday, self.view)
        self.assertEqual(embed.scope, "daily")
        self.assertIsNone(embed.page_id)

    def test_embed_on_yesterdays_daily_shows_on_todays_daily(self):
        from knowledge.repositories import PageEmbeddedViewRepository

        yesterday = self._make_daily(date(2026, 4, 23))
        today = self._make_daily(date(2026, 4, 24))
        self._make_embed(yesterday, self.view)

        on_today = list(PageEmbeddedViewRepository.list_for_page(today))
        self.assertEqual(len(on_today), 1)
        self.assertEqual(on_today[0].saved_view, self.view)

    def test_re_embedding_same_view_from_different_daily_is_idempotent(self):
        yesterday = self._make_daily(date(2026, 4, 23))
        today = self._make_daily(date(2026, 4, 24))
        first = self._make_embed(yesterday, self.view)
        again = self._make_embed(today, self.view)
        self.assertEqual(first.uuid, again.uuid)
        self.assertEqual(
            PageEmbeddedView.objects.filter(user=self.user, scope="daily").count(),
            1,
        )

    def test_regular_page_embed_is_not_daily_scoped(self):
        embed = self._make_embed(self.page, self.view)
        self.assertEqual(embed.scope, "page")
        self.assertEqual(embed.page_id, self.page.id)

    def test_daily_scoped_embed_does_not_show_on_regular_page(self):
        from knowledge.repositories import PageEmbeddedViewRepository

        yesterday = self._make_daily(date(2026, 4, 23))
        self._make_embed(yesterday, self.view)
        on_regular = list(PageEmbeddedViewRepository.list_for_page(self.page))
        self.assertEqual(on_regular, [])

    def test_reorder_operates_on_daily_bucket(self):
        from knowledge.repositories import PageEmbeddedViewRepository

        yesterday = self._make_daily(date(2026, 4, 23))
        today = self._make_daily(date(2026, 4, 24))
        view_a = SavedView.objects.create(
            user=self.user, name="A", slug="va", filter={}
        )
        view_b = SavedView.objects.create(
            user=self.user, name="B", slug="vb", filter={}
        )
        a = self._make_embed(yesterday, view_a)
        b = self._make_embed(yesterday, view_b)
        self.assertEqual(a.order, 0)
        self.assertEqual(b.order, 1)

        form = ReorderPageEmbeddedViewsForm(
            {
                "user": self.user.id,
                "page_uuid": str(today.uuid),
                "ordered_uuids": [str(b.uuid), str(a.uuid)],
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        ReorderPageEmbeddedViewsCommand(form).execute()

        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(b.order, 0)
        self.assertEqual(a.order, 1)

        on_today = list(PageEmbeddedViewRepository.list_for_page(today))
        self.assertEqual([e.uuid for e in on_today], [b.uuid, a.uuid])
