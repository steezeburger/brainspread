"""Tests for the SavedView + PageEmbeddedView tools wired into the chat.

Read tools (always-on): list_saved_views, get_saved_view, run_saved_view,
list_page_embedded_views.

Write tools (gated by allow_writes / auto_approve_writes — the approval
pause flow itself is exercised in test_approval_flow.py):
create_saved_view, update_saved_view, delete_saved_view,
duplicate_saved_view, embed_view_on_page, delete_page_embed.

The executor is a thin shim, so these tests focus on argument-shape
translation, the read/write split, and a few end-to-end happy-paths
that prove the tool actually round-trips through the matching command.
"""

from typing import Optional

from django.test import TestCase

from ai_chat.tools.notes_tool_executor import NotesToolExecutor
from core.test.helpers import UserFactory
from knowledge.models import (
    SYSTEM_VIEW_OVERDUE,
    PageEmbeddedView,
    SavedView,
)
from knowledge.services.system_views import seed_system_views_for_user
from knowledge.test.helpers import BlockFactory, PageFactory


def _readonly(user) -> NotesToolExecutor:
    return NotesToolExecutor(user)


def _writable(user, current_page_uuid: Optional[str] = None) -> NotesToolExecutor:
    return NotesToolExecutor(
        user,
        allow_writes=True,
        auto_approve_writes=True,
        current_page_uuid=current_page_uuid,
    )


class SavedViewReadToolsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="views@example.com", timezone="UTC")
        cls.page = PageFactory(user=cls.user, title="Inbox", slug="inbox")
        seed_system_views_for_user(cls.user)

    def test_list_returns_system_views_first(self):
        exec_ = _readonly(self.user)
        result = exec_.execute("list_saved_views", {})
        views = result["views"]
        # Both seeded system views show up; system flag is True for them.
        slugs = [v["slug"] for v in views]
        self.assertIn(SYSTEM_VIEW_OVERDUE, slugs)
        self.assertTrue(views[0]["is_system"])

    def test_get_by_slug(self):
        exec_ = _readonly(self.user)
        result = exec_.execute("get_saved_view", {"slug": SYSTEM_VIEW_OVERDUE})
        self.assertEqual(result["slug"], SYSTEM_VIEW_OVERDUE)

    def test_get_requires_slug_or_uuid(self):
        exec_ = _readonly(self.user)
        result = exec_.execute("get_saved_view", {})
        self.assertIn("error", result)

    def test_run_inline_filter_dry_run(self):
        # No SavedView created — the inline-draft path lets the LLM
        # propose a filter and preview matches before saving.
        match = BlockFactory(
            user=self.user, page=self.page, block_type="todo", content="x"
        )
        BlockFactory(user=self.user, page=self.page, block_type="bullet", content="y")
        exec_ = _readonly(self.user)
        result = exec_.execute("run_saved_view", {"filter": {"block_type": "todo"}})
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["uuid"], str(match.uuid))
        self.assertIsNone(result["view"])

    def test_run_inline_filter_compile_error_surfaces(self):
        exec_ = _readonly(self.user)
        result = exec_.execute("run_saved_view", {"filter": {"never_heard_of_it": 1}})
        self.assertIn("error", result)
        self.assertIn("filter compile error", result["error"])

    def test_run_rejects_more_than_one_target(self):
        exec_ = _readonly(self.user)
        result = exec_.execute(
            "run_saved_view",
            {"slug": "overdue", "filter": {"block_type": "todo"}},
        )
        self.assertIn("error", result)

    def test_list_page_embedded_views_by_slug(self):
        view = SavedView.objects.get(
            user=self.user, slug=SYSTEM_VIEW_OVERDUE, is_system=True
        )
        PageEmbeddedView.objects.create(
            user=self.user, page=self.page, saved_view=view, order=0
        )
        exec_ = _readonly(self.user)
        result = exec_.execute("list_page_embedded_views", {"page_slug": "inbox"})
        self.assertEqual(result["page"]["slug"], "inbox")
        self.assertEqual(len(result["embeds"]), 1)
        self.assertEqual(result["embeds"][0]["saved_view"]["slug"], SYSTEM_VIEW_OVERDUE)


class SavedViewWriteToolsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="vw@example.com", timezone="UTC")
        cls.page = PageFactory(user=cls.user, title="Notes", slug="notes")
        seed_system_views_for_user(cls.user)

    def test_create_view_round_trips(self):
        exec_ = _writable(self.user)
        result = exec_.execute(
            "create_saved_view",
            {"name": "Open todos", "filter": {"block_type": "todo"}},
        )
        self.assertTrue(result["created"])
        self.assertEqual(result["view"]["slug"], "open-todos")
        self.assertTrue(SavedView.objects.filter(slug="open-todos").exists())

    def test_create_rejects_invalid_filter(self):
        exec_ = _writable(self.user)
        result = exec_.execute(
            "create_saved_view",
            {"name": "Bad", "filter": {"never_heard_of_it": 1}},
        )
        self.assertIn("error", result)

    def test_update_then_delete(self):
        exec_ = _writable(self.user)
        view = SavedView.objects.create(
            user=self.user,
            name="Drafts",
            slug="drafts",
            filter={"block_type": "bullet"},
        )
        upd = exec_.execute(
            "update_saved_view",
            {"uuid": str(view.uuid), "name": "Renamed"},
        )
        self.assertTrue(upd["updated"])
        self.assertEqual(upd["view"]["name"], "Renamed")

        delete = exec_.execute("delete_saved_view", {"uuid": str(view.uuid)})
        self.assertTrue(delete["deleted"])
        self.assertFalse(SavedView.objects.filter(uuid=view.uuid).exists())

    def test_cannot_delete_system_view(self):
        exec_ = _writable(self.user)
        sys_view = SavedView.objects.get(
            user=self.user, slug=SYSTEM_VIEW_OVERDUE, is_system=True
        )
        result = exec_.execute("delete_saved_view", {"uuid": str(sys_view.uuid)})
        self.assertIn("error", result)
        self.assertTrue(SavedView.objects.filter(uuid=sys_view.uuid).exists())

    def test_duplicate_system_view(self):
        exec_ = _writable(self.user)
        sys_view = SavedView.objects.get(
            user=self.user, slug=SYSTEM_VIEW_OVERDUE, is_system=True
        )
        result = exec_.execute("duplicate_saved_view", {"uuid": str(sys_view.uuid)})
        self.assertTrue(result["duplicated"])
        self.assertFalse(result["view"]["is_system"])

    def test_embed_and_delete(self):
        exec_ = _writable(self.user)
        view = SavedView.objects.get(
            user=self.user, slug=SYSTEM_VIEW_OVERDUE, is_system=True
        )
        embed_result = exec_.execute(
            "embed_view_on_page",
            {
                "page_uuid": str(self.page.uuid),
                "saved_view_uuid": str(view.uuid),
            },
        )
        self.assertTrue(embed_result["embedded"])
        embed_uuid = embed_result["embed"]["uuid"]
        self.assertTrue(PageEmbeddedView.objects.filter(uuid=embed_uuid).exists())

        # Idempotent — re-embedding same (page, view) returns the same uuid
        # without creating a duplicate row.
        again = exec_.execute(
            "embed_view_on_page",
            {
                "page_uuid": str(self.page.uuid),
                "saved_view_uuid": str(view.uuid),
            },
        )
        self.assertEqual(again["embed"]["uuid"], embed_uuid)
        self.assertEqual(PageEmbeddedView.objects.filter(page=self.page).count(), 1)

        delete = exec_.execute("delete_page_embed", {"embed_uuid": embed_uuid})
        self.assertTrue(delete["deleted"])
        self.assertFalse(PageEmbeddedView.objects.filter(uuid=embed_uuid).exists())


class ReadWriteSeparationTests(TestCase):
    """The new write tools must be unknown to a read-only executor and the
    new read tools must always work."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="sep@example.com", timezone="UTC")
        seed_system_views_for_user(cls.user)

    def test_read_tools_known_on_read_only_executor(self):
        exec_ = _readonly(self.user)
        for name in (
            "list_saved_views",
            "get_saved_view",
            "run_saved_view",
            "list_page_embedded_views",
        ):
            self.assertTrue(exec_.is_known(name), name)

    def test_write_tools_unknown_on_read_only_executor(self):
        exec_ = _readonly(self.user)
        for name in (
            "create_saved_view",
            "update_saved_view",
            "delete_saved_view",
            "duplicate_saved_view",
            "embed_view_on_page",
            "delete_page_embed",
        ):
            self.assertFalse(exec_.is_known(name), name)

    def test_write_tools_known_on_writable_executor(self):
        exec_ = _writable(self.user)
        for name in (
            "create_saved_view",
            "update_saved_view",
            "delete_saved_view",
            "duplicate_saved_view",
            "embed_view_on_page",
            "delete_page_embed",
        ):
            self.assertTrue(exec_.is_known(name), name)
