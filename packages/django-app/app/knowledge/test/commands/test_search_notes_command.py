from django.test import TestCase

from knowledge.commands import SearchNotesCommand
from knowledge.forms import SearchNotesForm

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestSearchNotesCommand(TestCase):
    """The search_notes tool the LLM calls. Coverage exists primarily
    for the tag-aware behavior added to fix the 'what are my favorite
    fruits?' miss — when the user organized data as #fruits hashtags
    on a page rather than literal "fruit" text, a content-only ILIKE
    used to return zero. The tool now also matches via the M2M tag
    relationship so the model can find that data."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.other_user = UserFactory()

        # The tag page #fruits — this is what hashtag-tagged blocks
        # link to via the Block.pages M2M.
        cls.fruits_tag_page = PageFactory(
            user=cls.user, title="#fruits", slug="fruits", page_type="tag"
        )
        cls.favorites_page = PageFactory(
            user=cls.user, title="favorite things", slug="favorite-things"
        )

        # Block whose literal content has neither "fruit" nor "favorite"
        # in plain text — only hashtags. Pre-fix this returned zero for
        # search_notes("fruit").
        cls.banana_block = BlockFactory(
            user=cls.user, page=cls.favorites_page, content="#banana #fruits"
        )
        cls.banana_block.pages.add(cls.fruits_tag_page)

        # A second block on a totally different page, also tagged
        # #fruits — confirms the tag join finds it too.
        unrelated_page = PageFactory(
            user=cls.user, title="grocery list", slug="grocery-list"
        )
        cls.apple_block = BlockFactory(
            user=cls.user, page=unrelated_page, content="apple #fruits"
        )
        cls.apple_block.pages.add(cls.fruits_tag_page)

        # Noise: another block that shouldn't match a fruit search.
        cls.unrelated_block = BlockFactory(
            user=cls.user, page=unrelated_page, content="buy paper towels"
        )

        # Cross-user safety: another user has a block tagged #fruits
        # too. It must never appear in this user's search results.
        other_tag = PageFactory(
            user=cls.other_user, title="#fruits", slug="fruits", page_type="tag"
        )
        other_page = PageFactory(user=cls.other_user, title="theirs", slug="theirs")
        cls.stranger_block = BlockFactory(
            user=cls.other_user, page=other_page, content="kiwi #fruits"
        )
        cls.stranger_block.pages.add(other_tag)

    def _run(self, query: str, user=None):
        form = SearchNotesForm(
            {"user": (user or self.user).id, "query": query, "limit": 25}
        )
        self.assertTrue(form.is_valid(), form.errors)
        return SearchNotesCommand(form).execute()

    def test_substring_in_content_still_matches(self):
        # Sanity: the original behavior is preserved.
        result = self._run("apple")
        block_uuids = {entry["block_uuid"] for entry in result["results"]}
        self.assertIn(str(self.apple_block.uuid), block_uuids)

    def test_query_matches_via_tag_page_slug(self):
        # The motivating case: #banana #fruits / #fruits as a tag
        # page — query "fruit" should pick up both tagged blocks even
        # when "fruit" is only in the hashtag.
        result = self._run("fruit")
        block_uuids = {entry["block_uuid"] for entry in result["results"]}
        self.assertIn(str(self.banana_block.uuid), block_uuids)
        self.assertIn(str(self.apple_block.uuid), block_uuids)

    def test_query_does_not_match_unrelated_block(self):
        result = self._run("fruit")
        block_uuids = {entry["block_uuid"] for entry in result["results"]}
        self.assertNotIn(str(self.unrelated_block.uuid), block_uuids)

    def test_results_distinct_when_block_has_multiple_matching_tags(self):
        # A block tagged with two pages both matching the query
        # should still appear once. Exercises the .distinct() guard.
        herbs_tag = PageFactory(
            user=self.user, title="#fruits-extra", slug="fruits-extra", page_type="tag"
        )
        self.banana_block.pages.add(herbs_tag)
        result = self._run("fruit")
        block_uuids = [entry["block_uuid"] for entry in result["results"]]
        self.assertEqual(len(block_uuids), len(set(block_uuids)))

    def test_does_not_leak_across_users(self):
        result = self._run("fruit")
        block_uuids = {entry["block_uuid"] for entry in result["results"]}
        self.assertNotIn(str(self.stranger_block.uuid), block_uuids)

    def test_other_user_can_search_their_own(self):
        result = self._run("fruit", user=self.other_user)
        block_uuids = {entry["block_uuid"] for entry in result["results"]}
        self.assertEqual(block_uuids, {str(self.stranger_block.uuid)})
