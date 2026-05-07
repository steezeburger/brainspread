from django.test import TestCase

from knowledge.commands import SyncBlockTagsCommand
from knowledge.forms import SyncBlockTagsForm
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
