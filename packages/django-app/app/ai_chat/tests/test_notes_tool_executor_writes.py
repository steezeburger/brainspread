from django.test import TestCase

from ai_chat.tools.notes_tool_executor import NotesToolExecutor
from core.test.helpers import UserFactory
from knowledge.models import Block, Page
from knowledge.test.helpers import BlockFactory, PageFactory


class NotesToolExecutorWriteTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="writes@example.com")
        cls.other_user = UserFactory(email="writes-other@example.com")
        cls.page = PageFactory(user=cls.user, title="Inbox", slug="inbox")
        cls.other_page = PageFactory(user=cls.user, title="Done", slug="done")
        cls.block = BlockFactory(
            user=cls.user, page=cls.page, content="original", block_type="bullet"
        )

    def test_is_known_respects_allow_writes(self):
        read_only = NotesToolExecutor(self.user, allow_writes=False)
        writable = NotesToolExecutor(self.user, allow_writes=True)

        self.assertTrue(read_only.is_known("search_notes"))
        self.assertFalse(read_only.is_known("create_block"))
        self.assertFalse(read_only.is_known("create_page"))
        self.assertFalse(read_only.is_known("edit_block"))
        self.assertTrue(writable.is_known("create_page"))
        self.assertTrue(writable.is_known("create_block"))
        self.assertTrue(writable.is_known("edit_block"))
        self.assertTrue(writable.is_known("move_blocks"))

    def test_requires_approval_only_for_writes(self):
        ex = NotesToolExecutor(self.user, allow_writes=True)

        self.assertFalse(ex.requires_approval("search_notes"))
        self.assertTrue(ex.requires_approval("create_page"))
        self.assertTrue(ex.requires_approval("create_block"))
        self.assertTrue(ex.requires_approval("edit_block"))
        self.assertTrue(ex.requires_approval("move_blocks"))

    def test_auto_approve_writes_skips_approval_gate(self):
        # Opt-in: when auto_approve_writes is True, requires_approval
        # returns False for every tool, so the service runs them inline
        # like reads. is_known is unchanged.
        ex = NotesToolExecutor(self.user, allow_writes=True, auto_approve_writes=True)

        self.assertFalse(ex.requires_approval("create_block"))
        self.assertFalse(ex.requires_approval("edit_block"))
        self.assertFalse(ex.requires_approval("move_blocks"))
        self.assertFalse(ex.requires_approval("create_page"))
        self.assertTrue(ex.is_known("edit_block"))

    def test_create_page_creates_page_for_user(self):
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute("create_page", {"title": "Roadmap 2026"})

        self.assertTrue(result.get("created"))
        self.assertEqual(result["page"]["title"], "Roadmap 2026")
        self.assertEqual(result["page"]["page_type"], "page")
        page = Page.objects.get(user=self.user, title="Roadmap 2026")
        # Body content lives in Block rows. Page.whiteboard_snapshot is
        # whiteboard-only and stays empty for regular pages.
        self.assertEqual(page.whiteboard_snapshot, "")

    def test_create_page_rejects_daily_type(self):
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute("create_page", {"title": "Today", "page_type": "daily"})

        self.assertIn("error", result)
        self.assertFalse(Page.objects.filter(user=self.user, title="Today").exists())

    def test_create_page_rejects_whiteboard_type(self):
        # Whiteboards need a tldraw snapshot the model can't produce.
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "create_page", {"title": "Sketch", "page_type": "whiteboard"}
        )

        self.assertIn("error", result)
        self.assertFalse(Page.objects.filter(user=self.user, title="Sketch").exists())

    def test_create_page_requires_title(self):
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute("create_page", {"title": "   "})

        self.assertIn("error", result)

    def test_create_block_adds_block_to_page(self):
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "create_block",
            {
                "page_uuid": str(self.page.uuid),
                "content": "new item",
                "block_type": "todo",
            },
        )

        self.assertTrue(result.get("created"))
        self.assertEqual(result["block"]["content"], "new item")
        self.assertEqual(result["block"]["block_type"], "todo")
        self.assertTrue(
            Block.objects.filter(
                user=self.user, page=self.page, content="new item"
            ).exists()
        )

    def test_create_block_scopes_to_user(self):
        ex = NotesToolExecutor(self.other_user, allow_writes=True)

        # The other user can't reference a page they don't own.
        result = ex.execute(
            "create_block",
            {"page_uuid": str(self.page.uuid), "content": "nope"},
        )

        self.assertIn("error", result)
        self.assertFalse(
            Block.objects.filter(user=self.other_user, content="nope").exists()
        )

    def test_edit_block_updates_content(self):
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "edit_block",
            {"block_uuid": str(self.block.uuid), "content": "updated"},
        )

        self.assertTrue(result.get("updated"))
        self.block.refresh_from_db()
        self.assertEqual(self.block.content, "updated")

    def test_edit_block_preserves_parent_when_only_changing_content(self):
        # Regression: UpdateBlockCommand orphans a block to root if "parent"
        # is missing from the form. The executor must always pass the
        # current parent unless the caller is explicitly re-parenting.
        parent = BlockFactory(user=self.user, page=self.page, content="parent")
        child = BlockFactory(
            user=self.user, page=self.page, parent=parent, content="child"
        )
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "edit_block",
            {"block_uuid": str(child.uuid), "content": "child renamed"},
        )

        self.assertTrue(result.get("updated"))
        child.refresh_from_db()
        self.assertEqual(child.content, "child renamed")
        self.assertEqual(child.parent_id, parent.id)

    def test_edit_block_can_re_parent_to_another_block(self):
        new_parent = BlockFactory(user=self.user, page=self.page, content="new parent")
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "edit_block",
            {
                "block_uuid": str(self.block.uuid),
                "parent_uuid": str(new_parent.uuid),
            },
        )

        self.assertTrue(result.get("updated"))
        self.block.refresh_from_db()
        self.assertEqual(self.block.parent_id, new_parent.id)

    def test_edit_block_can_root_with_explicit_null_parent(self):
        parent = BlockFactory(user=self.user, page=self.page, content="parent")
        nested = BlockFactory(
            user=self.user, page=self.page, parent=parent, content="nested"
        )
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "edit_block",
            {"block_uuid": str(nested.uuid), "parent_uuid": None},
        )

        self.assertTrue(result.get("updated"))
        nested.refresh_from_db()
        self.assertIsNone(nested.parent_id)

    def test_edit_block_rejects_parent_on_different_page(self):
        other_page = PageFactory(user=self.user, title="Other", slug="other")
        wrong_parent = BlockFactory(
            user=self.user, page=other_page, content="elsewhere"
        )
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "edit_block",
            {
                "block_uuid": str(self.block.uuid),
                "parent_uuid": str(wrong_parent.uuid),
            },
        )

        self.assertIn("error", result)
        self.block.refresh_from_db()
        self.assertIsNone(self.block.parent_id)

    def test_edit_block_no_op_payload_returns_error(self):
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute("edit_block", {"block_uuid": str(self.block.uuid)})

        self.assertIn("error", result)

    def test_edit_block_rejects_other_users_block(self):
        ex = NotesToolExecutor(self.other_user, allow_writes=True)

        result = ex.execute(
            "edit_block",
            {"block_uuid": str(self.block.uuid), "content": "hacked"},
        )

        self.assertIn("error", result)
        self.block.refresh_from_db()
        self.assertEqual(self.block.content, "original")

    def test_reorder_blocks_updates_orders(self):
        a = BlockFactory(user=self.user, page=self.page, content="a", order=0)
        b = BlockFactory(user=self.user, page=self.page, content="b", order=1)
        c = BlockFactory(user=self.user, page=self.page, content="c", order=2)
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "reorder_blocks",
            {
                "blocks": [
                    {"block_uuid": str(c.uuid), "order": 0},
                    {"block_uuid": str(a.uuid), "order": 1},
                    {"block_uuid": str(b.uuid), "order": 2},
                ]
            },
        )

        self.assertTrue(result.get("reordered"))
        self.assertEqual(result["count"], 3)
        a.refresh_from_db()
        b.refresh_from_db()
        c.refresh_from_db()
        self.assertEqual(a.order, 1)
        self.assertEqual(b.order, 2)
        self.assertEqual(c.order, 0)

    def test_reorder_blocks_rejects_other_users_block(self):
        a = BlockFactory(user=self.user, page=self.page, content="a", order=0)
        foreign = BlockFactory(
            user=self.other_user,
            page=PageFactory(user=self.other_user, title="X", slug="x"),
            content="x",
        )
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "reorder_blocks",
            {
                "blocks": [
                    {"block_uuid": str(a.uuid), "order": 0},
                    {"block_uuid": str(foreign.uuid), "order": 1},
                ]
            },
        )

        self.assertIn("error", result)

    def test_move_blocks_changes_page(self):
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "move_blocks",
            {
                "block_uuids": [str(self.block.uuid)],
                "target_page_uuid": str(self.other_page.uuid),
            },
        )

        self.assertTrue(result.get("moved"))
        self.block.refresh_from_db()
        self.assertEqual(self.block.page_id, self.other_page.id)

    def test_move_blocks_reports_missing(self):
        ex = NotesToolExecutor(self.user, allow_writes=True)

        result = ex.execute(
            "move_blocks",
            {
                "block_uuids": ["00000000-0000-0000-0000-000000000000"],
                "target_page_uuid": str(self.other_page.uuid),
            },
        )

        self.assertIn("error", result)
