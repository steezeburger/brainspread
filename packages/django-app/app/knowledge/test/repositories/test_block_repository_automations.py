from django.test import TestCase

from knowledge.repositories import BlockRepository

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestGetAutomationBlocks(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.tag_page = PageFactory(user=cls.user, title="automation", slug="automation")

    def test_finds_m2m_tagged_block(self):
        page = PageFactory(user=self.user, title="Notes", slug="notes")
        block = BlockFactory(user=self.user, page=page, content="x #automation")
        block.pages.add(self.tag_page)

        found = BlockRepository.get_automation_blocks(self.user)

        self.assertEqual([b.pk for b in found], [block.pk])

    def test_finds_block_living_on_automation_page(self):
        # Matching has_tag semantics: a block ON a page with the tag's
        # slug counts even without the M2M — a seeded "Automations" page
        # shouldn't require retyping #automation on every block.
        block = BlockFactory(user=self.user, page=self.tag_page, content="no hashtag")

        found = BlockRepository.get_automation_blocks(self.user)

        self.assertEqual([b.pk for b in found], [block.pk])

    def test_excludes_template_page_blocks(self):
        # An #automation block inside a template is a dormant blueprint;
        # it must not fire until the template is applied to a real page.
        template = PageFactory(
            user=self.user,
            title="Morning pack",
            slug="morning-pack",
            page_type="template",
        )
        block = BlockFactory(user=self.user, page=template, content="x #automation")
        block.pages.add(self.tag_page)

        found = BlockRepository.get_automation_blocks(self.user)

        self.assertEqual(found, [])

    def test_scopes_to_user_and_deduplicates(self):
        other = UserFactory()
        other_tag_page = PageFactory(user=other, title="automation", slug="automation")
        other_page = PageFactory(user=other, title="Notes", slug="notes")
        other_block = BlockFactory(user=other, page=other_page, content="#automation")
        other_block.pages.add(other_tag_page)

        # Block both ON the automation page AND M2M-tagged — must appear once.
        block = BlockFactory(user=self.user, page=self.tag_page, content="#automation")
        block.pages.add(self.tag_page)

        found = BlockRepository.get_automation_blocks(self.user)

        self.assertEqual([b.pk for b in found], [block.pk])
