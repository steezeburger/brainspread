from django.test import TestCase

from knowledge.commands import DeletePageCommand, SyncBlockTagsCommand
from knowledge.forms import DeletePageForm, SyncBlockTagsForm
from knowledge.models import Page

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestSyncBlockTagsCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def _run(self, content: str):
        block = BlockFactory(user=self.user, page=self.page, content=content)
        form = SyncBlockTagsForm(
            {"user": self.user.id, "block": str(block.uuid), "content": content}
        )
        self.assertTrue(form.is_valid(), msg=form.errors)
        SyncBlockTagsCommand(form).execute()
        return block

    def _resync(self, block, content: str):
        """Re-run the command against an already-tagged block, as if its
        content were edited (mirrors update_block_command's retagging)."""
        block.content = content
        block.save()
        form = SyncBlockTagsForm(
            {"user": self.user.id, "block": str(block.uuid), "content": content}
        )
        self.assertTrue(form.is_valid(), msg=form.errors)
        SyncBlockTagsCommand(form).execute()
        return block

    def _tag_slugs(self, block):
        return set(block.pages.values_list("slug", flat=True))

    def test_creates_pages_for_plain_hashtags(self):
        block = self._run("Buy #groceries and #food today")
        self.assertEqual(self._tag_slugs(block), {"groceries", "food"})

    def test_skips_hashtags_inside_inline_code(self):
        block = self._run("see `#include <stdio.h>` and `#define X 1`")
        self.assertEqual(self._tag_slugs(block), set())
        self.assertFalse(Page.objects.filter(slug="include", user=self.user).exists())
        self.assertFalse(Page.objects.filter(slug="define", user=self.user).exists())

    def test_skips_hashtags_inside_fenced_code_block(self):
        content = "before\n```c\n#include <stdio.h>\n#define X 1\n```\nafter"
        block = self._run(content)
        self.assertEqual(self._tag_slugs(block), set())

    def test_extracts_hashtags_outside_code_when_code_present(self):
        content = "tag #real here, but `#fake` in code"
        block = self._run(content)
        self.assertEqual(self._tag_slugs(block), {"real"})
        self.assertFalse(Page.objects.filter(slug="fake", user=self.user).exists())

    def test_retagging_a_soft_deleted_tag_page_revives_it(self):
        # Regression test for the manual-QA follow-up to #242: type
        # #food-log2 (creates the tag page), edit the block to drop the
        # tag, delete the food-log2 page (Trash), then type #food-log2
        # again. This used to silently reattach the block to the dead
        # page instead of reviving or recreating it, so nothing visible
        # happened.
        block = self._run("#food-log2")
        tag_page = Page.objects.get(slug="food-log2", user=self.user)
        content_block = BlockFactory(
            user=self.user, page=tag_page, content="some content on the tag page"
        )

        self._resync(block, "no tag anymore")
        delete_form = DeletePageForm({"user": self.user.id, "page": tag_page.uuid})
        self.assertTrue(delete_form.is_valid(), delete_form.errors)
        DeletePageCommand(delete_form).execute()  # cascades to content_block
        tag_page.refresh_from_db()
        content_block.refresh_from_db()
        self.assertFalse(tag_page.is_active)
        self.assertFalse(content_block.is_active)

        block = self._resync(block, "#food-log2")

        tag_page.refresh_from_db()
        content_block.refresh_from_db()
        self.assertTrue(tag_page.is_active)
        self.assertIsNone(tag_page.deleted_at)
        self.assertTrue(content_block.is_active)
        self.assertEqual(self._tag_slugs(block), {"food-log2"})
        self.assertEqual(
            Page.objects.filter(slug="food-log2", user=self.user).count(), 1
        )
