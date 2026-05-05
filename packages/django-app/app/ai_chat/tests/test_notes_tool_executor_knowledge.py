"""Tests for the read-only knowledge-graph + meta tools added in #107.

- get_backlinks (page-targeted)
- get_tag_graph
- get_recent_activity
- get_chat_history_summary
- get_user_preferences
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from ai_chat.models import (
    AIModel,
    AIProvider,
    ChatMessage,
    ChatSession,
    UserAISettings,
)
from ai_chat.tools.notes_tool_executor import NotesToolExecutor
from core.test.helpers import UserFactory
from knowledge.test.helpers import BlockFactory, PageFactory


def _executor(user) -> NotesToolExecutor:
    return NotesToolExecutor(user, allow_writes=False)


class GetBacklinksTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="backlinks@example.com")
        cls.other = UserFactory(email="backlinks-other@example.com")
        cls.target = PageFactory(
            user=cls.user, title="Project Alpha", slug="project-alpha"
        )
        # Source page hosts the linking + tagged blocks
        cls.source_page = PageFactory(user=cls.user, title="Notes", slug="notes")
        cls.linker = BlockFactory(
            user=cls.user,
            page=cls.source_page,
            content="see [[Project Alpha]] for details",
        )
        cls.tagger = BlockFactory(
            user=cls.user, page=cls.source_page, content="follow up"
        )
        cls.tagger.pages.add(cls.target)
        cls.unrelated = BlockFactory(
            user=cls.user, page=cls.source_page, content="unrelated"
        )
        # Other user's data must not leak
        other_page = PageFactory(user=cls.other, title="Project Alpha")
        BlockFactory(user=cls.other, page=other_page, content="[[Project Alpha]]")

    def test_returns_content_links_and_tag_links(self):
        result = _executor(self.user).execute(
            "get_backlinks", {"page_uuid": str(self.target.uuid)}
        )
        block_uuids = {row["block_uuid"] for row in result["results"]}
        self.assertIn(str(self.linker.uuid), block_uuids)
        self.assertIn(str(self.tagger.uuid), block_uuids)
        self.assertNotIn(str(self.unrelated.uuid), block_uuids)

    def test_marks_source_per_block(self):
        result = _executor(self.user).execute(
            "get_backlinks", {"page_uuid": str(self.target.uuid)}
        )
        by_uuid = {row["block_uuid"]: row for row in result["results"]}
        self.assertEqual(by_uuid[str(self.linker.uuid)]["sources"], ["content_link"])
        self.assertEqual(by_uuid[str(self.tagger.uuid)]["sources"], ["tag"])

    def test_user_isolation(self):
        # Looking up a page belonging to another user should fail validation.
        other_target = PageFactory(user=self.other, title="X")
        result = _executor(self.user).execute(
            "get_backlinks", {"page_uuid": str(other_target.uuid)}
        )
        self.assertIn("error", result)

    def test_empty_when_no_references(self):
        lonely = PageFactory(user=self.user, title="Lonely", slug="lonely")
        result = _executor(self.user).execute(
            "get_backlinks", {"page_uuid": str(lonely.uuid)}
        )
        self.assertEqual(result["count"], 0)


class GetTagGraphTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="tag-graph@example.com")
        cls.other = UserFactory(email="tag-graph-other@example.com")
        cls.host = PageFactory(user=cls.user, title="Notes")
        cls.tag_a = PageFactory(user=cls.user, title="topic-a", slug="topic-a")
        cls.tag_b = PageFactory(user=cls.user, title="topic-b", slug="topic-b")
        cls.tag_c = PageFactory(user=cls.user, title="topic-c", slug="topic-c")

        # 2 blocks tag both a and b — pair (a,b) shows up twice
        for _ in range(2):
            block = BlockFactory(user=cls.user, page=cls.host)
            block.pages.add(cls.tag_a, cls.tag_b)
        # 1 block tags a and c — pair (a,c) shows up once
        b = BlockFactory(user=cls.user, page=cls.host)
        b.pages.add(cls.tag_a, cls.tag_c)

        # Other user — must not show up in our graph
        other_host = PageFactory(user=cls.other, title="Other")
        other_a = PageFactory(user=cls.other, title="o-a")
        other_b = PageFactory(user=cls.other, title="o-b")
        ob = BlockFactory(user=cls.other, page=other_host)
        ob.pages.add(other_a, other_b)

    def test_pairs_ranked_by_shared_count(self):
        result = _executor(self.user).execute("get_tag_graph", {"min_shared": 1})
        # (a,b) = 2, (a,c) = 1
        self.assertEqual(result["count"], 2)
        first, second = result["results"]
        self.assertEqual(first["shared_count"], 2)
        self.assertEqual(second["shared_count"], 1)

    def test_min_shared_filters_below_threshold(self):
        result = _executor(self.user).execute("get_tag_graph", {"min_shared": 2})
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["shared_count"], 2)


class GetRecentActivityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="recent@example.com")
        cls.page_old = PageFactory(user=cls.user, title="old")
        cls.page_new = PageFactory(user=cls.user, title="new")
        cls.block_oldish = BlockFactory(
            user=cls.user, page=cls.page_old, content="oldish"
        )
        cls.block_newest = BlockFactory(
            user=cls.user, page=cls.page_new, content="newest"
        )

    def setUp(self):
        # auto_now bumps modified_at on save; freeze the values explicitly.
        now = timezone.now()
        from knowledge.models import Block, Page

        Page.objects.filter(pk=self.page_old.pk).update(
            modified_at=now - timedelta(days=2)
        )
        Page.objects.filter(pk=self.page_new.pk).update(
            modified_at=now - timedelta(seconds=10)
        )
        Block.objects.filter(pk=self.block_oldish.pk).update(
            modified_at=now - timedelta(days=1)
        )
        Block.objects.filter(pk=self.block_newest.pk).update(modified_at=now)

    def test_both_kind_returns_blocks_and_pages_sorted(self):
        result = _executor(self.user).execute("get_recent_activity", {"limit": 10})
        kinds_in_order = [item["kind"] for item in result["results"]]
        # newest block, then page-new, then oldish block, then page_old
        self.assertEqual(kinds_in_order[0], "block")
        self.assertEqual(result["results"][0]["uuid"], str(self.block_newest.uuid))

    def test_blocks_only(self):
        result = _executor(self.user).execute(
            "get_recent_activity", {"kind": "block", "limit": 10}
        )
        for item in result["results"]:
            self.assertEqual(item["kind"], "block")

    def test_pages_only(self):
        result = _executor(self.user).execute(
            "get_recent_activity", {"kind": "page", "limit": 10}
        )
        for item in result["results"]:
            self.assertEqual(item["kind"], "page")


class GetChatHistorySummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="history@example.com")
        cls.other = UserFactory(email="history-other@example.com")

        cls.session_old = ChatSession.objects.create(user=cls.user, title="")
        ChatMessage.objects.create(
            session=cls.session_old, role="user", content="how do i deploy?"
        )
        ChatMessage.objects.create(
            session=cls.session_old, role="assistant", content="run just deploy"
        )

        cls.session_new = ChatSession.objects.create(user=cls.user, title="")
        ChatMessage.objects.create(
            session=cls.session_new,
            role="user",
            content="x" * 250,  # Will be truncated in the summary
        )

        # Other user's session
        ChatSession.objects.create(user=cls.other, title="")

    def test_lists_user_sessions_newest_first(self):
        result = _executor(self.user).execute("get_chat_history_summary", {})
        self.assertEqual(result["count"], 2)
        self.assertEqual(
            result["results"][0]["session_uuid"], str(self.session_new.uuid)
        )

    def test_includes_message_count_and_truncated_summary(self):
        result = _executor(self.user).execute("get_chat_history_summary", {})
        by_uuid = {row["session_uuid"]: row for row in result["results"]}
        old_row = by_uuid[str(self.session_old.uuid)]
        new_row = by_uuid[str(self.session_new.uuid)]
        self.assertEqual(old_row["message_count"], 2)
        self.assertEqual(old_row["summary"], "how do i deploy?")
        self.assertEqual(new_row["message_count"], 1)
        self.assertTrue(new_row["summary"].endswith("..."))
        self.assertLessEqual(len(new_row["summary"]), 200)

    def test_user_isolation(self):
        result = _executor(self.user).execute("get_chat_history_summary", {})
        uuids = {row["session_uuid"] for row in result["results"]}
        # No other-user sessions
        for s in ChatSession.objects.filter(user=self.other):
            self.assertNotIn(str(s.uuid), uuids)


class GetUserPreferencesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(
            email="prefs@example.com",
            timezone="America/Los_Angeles",
            theme="purple",
            time_format="24h",
            discord_webhook_url="https://discord.com/api/webhooks/abc",
            discord_user_id="123456",
        )

    def test_returns_user_facing_settings(self):
        result = _executor(self.user).execute("get_user_preferences", {})
        self.assertEqual(result["timezone"], "America/Los_Angeles")
        self.assertEqual(result["theme"], "purple")
        self.assertEqual(result["time_format"], "24h")
        self.assertTrue(result["has_discord_webhook"])
        self.assertTrue(result["has_discord_user_id"])

    def test_does_not_leak_secrets(self):
        result = _executor(self.user).execute("get_user_preferences", {})
        self.assertNotIn("discord_webhook_url", result)
        self.assertNotIn("discord_user_id", result)
        self.assertNotIn("api_key", result)

    def test_preferred_model_label_when_set(self):
        provider = AIProvider.objects.create(
            name="anthropic", base_url="https://api.anthropic.com"
        )
        model = AIModel.objects.create(
            provider=provider, name="claude-test", display_name="Claude Test"
        )
        UserAISettings.objects.create(user=self.user, preferred_model=model)
        result = _executor(self.user).execute("get_user_preferences", {})
        self.assertEqual(result["preferred_model_label"], "Claude Test")

    def test_preferred_model_label_none_without_settings(self):
        # Fresh user, no UserAISettings row.
        u = UserFactory(email="no-prefs-set@example.com")
        result = _executor(u).execute("get_user_preferences", {})
        self.assertIsNone(result["preferred_model_label"])


class NewToolRegistrationTests(TestCase):
    """Smoke check: is_known + schema list reflect the new tools."""

    def setUp(self):
        self.user = UserFactory(email="reg-knowledge@example.com")

    def test_is_known_for_each_new_tool(self):
        ex = _executor(self.user)
        for name in (
            "get_backlinks",
            "get_tag_graph",
            "get_recent_activity",
            "get_chat_history_summary",
            "get_user_preferences",
        ):
            self.assertTrue(ex.is_known(name), name)
            self.assertFalse(ex.requires_approval(name), name)

    def test_anthropic_schema_includes_new_tools(self):
        from ai_chat.tools.notes_tools import anthropic_notes_tools

        names = {t["name"] for t in anthropic_notes_tools()}
        for name in (
            "get_backlinks",
            "get_tag_graph",
            "get_recent_activity",
            "get_chat_history_summary",
            "get_user_preferences",
        ):
            self.assertIn(name, names)
