from datetime import date

from django.test import TestCase

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestBlockToDictTags(TestCase):
    """BlockData["tags"] carries page identity, not just the slug.

    The move-to-page picker ranks a block's tag pages above its recents
    (issue #195), which only works if the tag entries are page-shaped —
    uuid + title, not a bare name.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.home = PageFactory(user=cls.user, title="Home", slug="home")
        cls.recipes = PageFactory(user=cls.user, title="Recipes", slug="recipes")

    def test_tag_entries_include_page_identity(self):
        block = BlockFactory(user=self.user, page=self.home, content="buy #recipes")
        block.pages.add(self.recipes)

        expected = {
            "name": "recipes",
            "uuid": str(self.recipes.uuid),
            "title": "Recipes",
            "page_type": "page",
            "color": "#007bff",
        }

        self.assertEqual(block.to_dict()["tags"], [expected])

    def test_own_page_and_dailies_are_not_tags(self):
        """get_tags() already filters these out — they'd be useless move
        suggestions (the block is on one and the picker pins today's
        daily itself)."""
        daily = PageFactory(
            user=self.user,
            title="2026-08-21",
            slug="2026-08-21",
            page_type="daily",
            date=date(2026, 8, 21),
        )
        block = BlockFactory(user=self.user, page=self.home, content="note")
        block.pages.add(self.home, daily, self.recipes)

        names = [tag["name"] for tag in block.to_dict()["tags"]]

        self.assertEqual(names, ["recipes"])

    def test_untagged_block_has_no_tags(self):
        block = BlockFactory(user=self.user, page=self.home, content="note")

        self.assertEqual(block.to_dict()["tags"], [])
