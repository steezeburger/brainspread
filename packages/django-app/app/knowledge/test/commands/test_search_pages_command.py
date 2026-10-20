from django.test import TestCase

from knowledge.commands import SearchPagesCommand
from knowledge.forms import SearchPagesForm

from ..helpers import PageFactory, UserFactory


class TestSearchPagesCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def _search(self, query: str, **extra):
        form = SearchPagesForm({"user": self.user.id, "query": query, **extra})
        self.assertTrue(form.is_valid(), form.errors)
        return SearchPagesCommand(form).execute()

    def test_excludes_soft_deleted_pages(self):
        # Regression test for #242: a tag page (created by typing
        # #food-log2 in a block) that later gets soft-deleted via the
        # Trash feature (#122) must not keep showing up as a hashtag
        # autocomplete suggestion.
        page = PageFactory(user=self.user, title="Food Log2", slug="food-log2")
        page.delete()  # soft delete
        self.assertFalse(page.is_active)

        result = self._search("foo")

        self.assertEqual(result["pages"], [])
        self.assertEqual(result["total_count"], 0)

    def test_includes_live_page_even_after_it_is_no_longer_tagged_in_any_block(self):
        # A page that was tagged in a block and later untagged (the block
        # content was edited to remove the reference) is still a live page
        # and should keep appearing in search results.
        page = PageFactory(user=self.user, title="Food Log2", slug="food-log2")

        result = self._search("foo")

        self.assertEqual(len(result["pages"]), 1)
        self.assertEqual(result["pages"][0]["title"], "Food Log2")
        self.assertEqual(result["total_count"], 1)

    def test_matches_by_slug_as_well_as_title(self):
        page = PageFactory(user=self.user, title="Grocery List", slug="grocery-list")

        result = self._search("grocery-l")

        self.assertEqual(len(result["pages"]), 1)
        self.assertEqual(result["pages"][0]["uuid"], str(page.uuid))

    def test_respects_page_type_filter(self):
        PageFactory(
            user=self.user,
            title="Food Template",
            slug="food-template",
            page_type="template",
        )
        PageFactory(
            user=self.user, title="Food Notes", slug="food-notes", page_type="page"
        )

        result = self._search("food", page_type="template")

        self.assertEqual(len(result["pages"]), 1)
        self.assertEqual(result["pages"][0]["title"], "Food Template")

    def test_excludes_unpublished_pages(self):
        PageFactory(
            user=self.user, title="Draft Page", slug="draft-page", is_published=False
        )

        result = self._search("draft")

        self.assertEqual(result["pages"], [])

    def test_scoped_to_requesting_user(self):
        other_user = UserFactory()
        PageFactory(user=other_user, title="Other User Page", slug="other-user-page")

        result = self._search("other")

        self.assertEqual(result["pages"], [])
