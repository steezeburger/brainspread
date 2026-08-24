from django.test import TestCase

from .helpers import BlockFactory, PageFactory, UserFactory


class TestBlockIsAutomation(TestCase):
    """Block.is_automation mirrors BlockRepository._automation_blocks_qs:
    tagged ``automation`` or living on the ``automation`` page, dormant
    inside templates. The ⋮ menu gates "run automation" on the
    serialized field, so these cases are the menu's contract."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.automation_page = PageFactory(
            user=cls.user, title="Automation", slug="automation"
        )
        cls.other_page = PageFactory(user=cls.user, title="Notes", slug="notes")

    def test_tagged_block_elsewhere_is_automation(self):
        block = BlockFactory(user=self.user, page=self.other_page, content="x")
        block.pages.add(self.automation_page)
        self.assertTrue(block.is_automation())
        self.assertTrue(block.to_dict()["is_automation"])

    def test_resident_block_without_tag_is_automation(self):
        block = BlockFactory(user=self.user, page=self.automation_page, content="x")
        self.assertTrue(block.is_automation())
        self.assertTrue(block.to_dict()["is_automation"])

    def test_resident_block_with_own_page_tag_is_automation(self):
        block = BlockFactory(
            user=self.user, page=self.automation_page, content="x #automation"
        )
        block.pages.add(self.automation_page)
        data = block.to_dict()
        self.assertTrue(data["is_automation"])
        # get_tags no longer hides the own-page tag from the API.
        self.assertIn("automation", [t["name"] for t in data["tags"]])

    def test_template_resident_block_is_dormant(self):
        template = PageFactory(
            user=self.user, title="Tpl", slug="tpl", page_type="template"
        )
        block = BlockFactory(user=self.user, page=template, content="x")
        block.pages.add(self.automation_page)
        self.assertFalse(block.is_automation())
        self.assertFalse(block.to_dict()["is_automation"])

    def test_plain_block_is_not_automation(self):
        block = BlockFactory(user=self.user, page=self.other_page, content="x")
        self.assertFalse(block.is_automation())
        self.assertFalse(block.to_dict()["is_automation"])

    def test_daily_links_still_excluded_from_tags(self):
        daily = PageFactory(
            user=self.user, page_type="daily", title="", slug="2026-08-24"
        )
        block = BlockFactory(user=self.user, page=self.other_page, content="x")
        block.pages.add(daily)
        self.assertEqual(block.get_tag_names(), [])
