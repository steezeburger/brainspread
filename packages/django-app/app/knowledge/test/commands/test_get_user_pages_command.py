from datetime import date, datetime

import pytz
from django.test import TestCase

from knowledge.commands import GetUserPagesCommand
from knowledge.forms import GetUserPagesForm
from knowledge.models import Page

from ..helpers import PageFactory, UserFactory


def _set_modified(page: Page, when: datetime) -> None:
    """Set modified_at explicitly; .update() bypasses auto_now."""
    Page.objects.filter(pk=page.pk).update(modified_at=when)


def _utc(*args: int) -> datetime:
    return pytz.UTC.localize(datetime(*args))


class TestGetUserPagesCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.other_user = UserFactory()

        cls.page_old = PageFactory(user=cls.user, title="Alpha", slug="alpha")
        cls.page_new = PageFactory(user=cls.user, title="Zulu", slug="zulu")
        cls.daily_old = PageFactory(
            user=cls.user,
            title="2026-06-01",
            slug="2026-06-01",
            page_type="daily",
            date=date(2026, 6, 1),
        )
        cls.daily_new = PageFactory(
            user=cls.user,
            title="2026-06-15",
            slug="2026-06-15",
            page_type="daily",
            date=date(2026, 6, 15),
        )
        cls.other_page = PageFactory(user=cls.other_user, title="Stranger")

        _set_modified(cls.page_old, _utc(2026, 6, 1))
        _set_modified(cls.page_new, _utc(2026, 6, 20))
        # The old daily was touched most recently — distinguishes
        # "date" ordering from "modified" ordering in the tests below.
        _set_modified(cls.daily_old, _utc(2026, 6, 25))
        _set_modified(cls.daily_new, _utc(2026, 6, 10))

    def _run(self, **params):
        data = {"user": self.user.id, **params}
        form = GetUserPagesForm(data)
        return GetUserPagesCommand(form).execute()

    def _slugs(self, result):
        return [p.slug for p in result["pages"]]

    def test_should_default_to_recently_modified_ordering(self):
        result = self._run()
        self.assertEqual(
            self._slugs(result),
            ["2026-06-01", "zulu", "2026-06-15", "alpha"],
        )
        self.assertEqual(result["total_count"], 4)
        self.assertFalse(result["has_more"])

    def test_should_order_by_title(self):
        result = self._run(order_by="title")
        self.assertEqual(
            self._slugs(result),
            ["2026-06-01", "2026-06-15", "alpha", "zulu"],
        )

    def test_should_order_by_date_with_undated_pages_last(self):
        result = self._run(order_by="date")
        self.assertEqual(
            self._slugs(result),
            ["2026-06-15", "2026-06-01", "zulu", "alpha"],
        )

    def test_should_reject_unknown_order_by(self):
        form = GetUserPagesForm({"user": self.user.id, "order_by": "bogus"})
        self.assertFalse(form.is_valid())
        self.assertIn("order_by", form.errors)

    def test_should_filter_by_page_type(self):
        result = self._run(page_type="daily")
        self.assertEqual(set(self._slugs(result)), {"2026-06-01", "2026-06-15"})
        self.assertEqual(result["total_count"], 2)

    def test_should_paginate_with_has_more(self):
        first = self._run(limit=3, offset=0)
        self.assertEqual(len(first["pages"]), 3)
        self.assertTrue(first["has_more"])

        rest = self._run(limit=3, offset=3)
        self.assertEqual(len(rest["pages"]), 1)
        self.assertFalse(rest["has_more"])
        self.assertEqual(rest["total_count"], 4)

    def test_should_filter_unpublished_when_published_only(self):
        unpublished = PageFactory(
            user=self.user, title="Draft", slug="draft", is_published=False
        )
        result = self._run(published_only="true")
        self.assertNotIn(unpublished.slug, self._slugs(result))

        result_all = self._run(published_only="false")
        self.assertIn(unpublished.slug, self._slugs(result_all))

    def test_should_not_leak_other_users_pages(self):
        result = self._run(limit=100)
        self.assertNotIn(self.other_page.slug, self._slugs(result))
