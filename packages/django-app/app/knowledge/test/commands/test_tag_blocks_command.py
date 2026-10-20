from django.test import TestCase

from knowledge.commands import TagBlocksCommand, UntagBlocksCommand
from knowledge.forms.tag_blocks_form import TagBlocksForm, UntagBlocksForm

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestTagBlocksCommand(TestCase):
    """Issue #261: tagging writes the #slug into the content so the tag
    is visible on the block and survives later edits."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)
        cls.work = PageFactory(user=cls.user, title="work", slug="work")
        cls.ideas = PageFactory(user=cls.user, title="ideas", slug="ideas")

    def _tag(self, block, *pages):
        form = TagBlocksForm(
            data={
                "user": self.user.id,
                "block_uuids": [str(block.uuid)],
                "page_uuids": [str(p.uuid) for p in pages],
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        result = TagBlocksCommand(form).execute()
        block.refresh_from_db()
        return result

    def _untag(self, block, *pages):
        form = UntagBlocksForm(
            data={
                "user": self.user.id,
                "block_uuids": [str(block.uuid)],
                "page_uuids": [str(p.uuid) for p in pages],
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        result = UntagBlocksCommand(form).execute()
        block.refresh_from_db()
        return result

    def test_tag_appends_hashtag_and_links(self):
        block = BlockFactory(user=self.user, page=self.page, content="task")

        result = self._tag(block, self.work)

        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(block.content, "task #work")
        self.assertIn(self.work, block.pages.all())

    def test_tag_is_idempotent(self):
        block = BlockFactory(user=self.user, page=self.page, content="task #work")

        self._tag(block, self.work)

        self.assertEqual(block.content, "task #work")

    def test_tag_goes_on_the_first_line(self):
        block = BlockFactory(user=self.user, page=self.page, content="task\nnotes")

        self._tag(block, self.work, self.ideas)

        self.assertEqual(block.content, "task #work #ideas\nnotes")

    def test_tag_keeps_todo_type(self):
        block = BlockFactory(
            user=self.user, page=self.page, block_type="todo", content="ship it"
        )

        self._tag(block, self.work)

        self.assertEqual(block.block_type, "todo")
        self.assertEqual(block.content, "TODO ship it #work")

    def test_tag_keeps_done_completed_at(self):
        block = BlockFactory(
            user=self.user, page=self.page, block_type="done", content="DONE x"
        )
        block.completed_at = block.created_at
        block.save()
        stamp = block.completed_at

        self._tag(block, self.work)

        self.assertEqual(block.block_type, "done")
        self.assertEqual(block.completed_at, stamp)

    def test_tag_leaves_code_content_alone(self):
        block = BlockFactory(
            user=self.user, page=self.page, block_type="code", content="x = 1"
        )

        self._tag(block, self.work)

        self.assertEqual(block.content, "x = 1")
        self.assertIn(self.work, block.pages.all())

    def test_untag_strips_hashtag_and_link(self):
        block = BlockFactory(user=self.user, page=self.page, content="task")
        self._tag(block, self.work)
        block.content = "task #work more"
        block.save()

        self._untag(block, self.work)

        self.assertEqual(block.content, "task more")
        self.assertNotIn(self.work, block.pages.all())

    def test_untag_removes_link_only_tag(self):
        block = BlockFactory(user=self.user, page=self.page, content="task")
        block.pages.add(self.work)

        self._untag(block, self.work)

        self.assertEqual(block.content, "task")
        self.assertNotIn(self.work, block.pages.all())
