from django.test import TestCase

from ai_chat.tools.notes_tool_executor import NotesToolExecutor
from core.test.helpers import UserFactory
from knowledge.test.helpers import BlockFactory, PageFactory


class NotesToolExecutorTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="notes-tools@example.com")
        cls.other_user = UserFactory(email="other@example.com")

        cls.page = PageFactory(user=cls.user, title="Project Alpha", slug="project-alpha")
        cls.block = BlockFactory(
            user=cls.user,
            page=cls.page,
            content="Follow up with design team",
            block_type="todo",
        )
        cls.child = BlockFactory(
            user=cls.user,
            page=cls.page,
            parent=cls.block,
            content="Confirm launch date",
        )
        # Noise that must not leak across users.
        BlockFactory(
            user=cls.other_user,
            page=PageFactory(user=cls.other_user, title="Other"),
            content="Follow up on launch",
        )

    def test_search_notes_scopes_to_user(self):
        executor = NotesToolExecutor(self.user)

        result = executor.execute("search_notes", {"query": "follow up"})

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["page_title"], "Project Alpha")
        self.assertEqual(result["results"][0]["block_type"], "todo")

    def test_get_page_by_title_returns_root_blocks(self):
        executor = NotesToolExecutor(self.user)

        result = executor.execute("get_page_by_title", {"title": "project alpha"})

        self.assertEqual(result["page"]["slug"], "project-alpha")
        self.assertEqual(len(result["blocks"]), 1)
        self.assertEqual(result["blocks"][0]["content"], "Follow up with design team")

    def test_get_block_by_id_returns_children(self):
        executor = NotesToolExecutor(self.user)

        result = executor.execute("get_block_by_id", {"block_uuid": str(self.block.uuid)})

        self.assertEqual(result["block"]["content"], "Follow up with design team")
        self.assertEqual(len(result["children"]), 1)
        self.assertEqual(result["children"][0]["content"], "Confirm launch date")

    def test_unknown_tool_returns_error(self):
        executor = NotesToolExecutor(self.user)

        result = executor.execute("delete_all_notes", {})

        self.assertIn("error", result)

    def test_is_known(self):
        executor = NotesToolExecutor(self.user)

        self.assertTrue(executor.is_known("search_notes"))
        self.assertTrue(executor.is_known("get_page_by_title"))
        self.assertTrue(executor.is_known("get_block_by_id"))
        self.assertFalse(executor.is_known("write_block"))
