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

    def test_dailies_are_not_tags(self):
        """Daily-note links aren't shown as hashtag chips — they'd be a
        useless move suggestion (the picker pins today's daily itself)."""
        daily = PageFactory(
            user=self.user,
            title="2026-08-21",
            slug="2026-08-21",
            page_type="daily",
            date=date(2026, 8, 21),
        )
        block = BlockFactory(user=self.user, page=self.home, content="note")
        block.pages.add(daily, self.recipes)

        names = [tag["name"] for tag in block.to_dict()["tags"]]

        self.assertEqual(names, ["recipes"])

    def test_own_page_is_a_tag(self):
        """A block living on a page it's also hashtag-linked to (e.g. an
        automation definition on the `automation` page carrying
        `#automation`) is genuinely tagged with it — get_tags() must not
        hide the block's own page (issue #217), or the serialized tag
        list lies to consumers like the run-automation menu."""
        block = BlockFactory(user=self.user, page=self.home, content="note #home")
        block.pages.add(self.home, self.recipes)

        names = [tag["name"] for tag in block.to_dict()["tags"]]

        self.assertEqual(names, ["home", "recipes"])

    def test_untagged_block_has_no_tags(self):
        block = BlockFactory(user=self.user, page=self.home, content="note")

        self.assertEqual(block.to_dict()["tags"], [])

    def test_archived_tag_page_is_not_a_tag(self):
        """A block tagged with a page that's since been soft-deleted
        shouldn't still render that tag as a chip — get_tags() filters
        `self.pages.all()` (an unfiltered M2M manager) by is_active
        itself, the same category of leak as #122's nested-block bug."""
        block = BlockFactory(user=self.user, page=self.home, content="note")
        block.pages.add(self.recipes)
        self.recipes.is_active = False
        self.recipes.save(update_fields=["is_active"])

        self.assertEqual(block.to_dict()["tags"], [])
