from importlib import import_module

from django.apps import apps
from django.test import TestCase

from ..helpers import BlockFactory, PageFactory, UserFactory

backfill_link_only_tags = import_module(
    "knowledge.migrations.0052_backfill_link_only_tags"
).backfill_link_only_tags


class TestBackfillLinkOnlyTags(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)
        cls.ideas = PageFactory(user=cls.user, title="ideas", slug="project-ideas")
        cls.work = PageFactory(user=cls.user, title="work", slug="work")

    def _block(self, content, block_type="bullet"):
        return BlockFactory(
            user=self.user, page=self.page, content=content, block_type=block_type
        )

    def test_writes_link_only_tags_into_first_line(self):
        block = self._block("TODO idea\nnotes", "todo")
        block.pages.add(self.ideas, self.work)

        backfill_link_only_tags(apps, None)

        block.refresh_from_db()
        self.assertEqual(block.content, "TODO idea #project-ideas #work\nnotes")

    def test_leaves_inline_tags_and_skipped_blocks_alone(self):
        tagged = self._block("thing #work")
        tagged.pages.add(self.work)
        code = self._block("x = 1", "code")
        code.pages.add(self.work)
        daily = PageFactory(user=self.user, page_type="daily")
        on_daily = self._block("journal")
        on_daily.pages.add(daily)
        automation = PageFactory(user=self.user, title="automation", slug="automation")
        auto = self._block("plain")
        auto.pages.add(automation)

        backfill_link_only_tags(apps, None)

        for block, expected in [
            (tagged, "thing #work"),
            (code, "x = 1"),
            (on_daily, "journal"),
            (auto, "plain"),
        ]:
            block.refresh_from_db()
            self.assertEqual(block.content, expected)
