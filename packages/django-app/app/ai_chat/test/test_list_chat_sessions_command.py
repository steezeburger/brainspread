from django.test import TestCase

from ai_chat.commands import ListChatSessionsCommand
from ai_chat.forms import ListChatSessionsForm
from core.test.helpers import UserFactory

from .helpers import ChatMessageFactory, ChatSessionFactory


class TestListChatSessionsCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.other_user = UserFactory()

        cls.session_titled = ChatSessionFactory(
            user=cls.user, title="Pinecone Recipes"
        )
        ChatMessageFactory(
            session=cls.session_titled,
            role="user",
            content="What's the best fertilizer schedule for tomatoes?",
        )

        cls.session_message = ChatSessionFactory(
            user=cls.user, title="General Chat"
        )
        ChatMessageFactory(
            session=cls.session_message,
            role="user",
            content="Tell me about pinecone propagation in dry climates.",
        )

        cls.session_unrelated = ChatSessionFactory(
            user=cls.user, title="Travel Plans"
        )
        ChatMessageFactory(
            session=cls.session_unrelated,
            role="user",
            content="Hotels near Lisbon for next month.",
        )

        cls.other_session = ChatSessionFactory(
            user=cls.other_user, title="pinecone gardener notes"
        )
        ChatMessageFactory(
            session=cls.other_session,
            role="user",
            content="pinecone pinecone pinecone",
        )

    def _run(self, user, search=""):
        form = ListChatSessionsForm({"user": user.id, "search": search})
        self.assertTrue(form.is_valid(), form.errors)
        return ListChatSessionsCommand(form).execute()

    def test_returns_all_sessions_when_search_blank(self):
        result = self._run(self.user)
        uuids = {entry["uuid"] for entry in result}
        self.assertEqual(
            uuids,
            {
                str(self.session_titled.uuid),
                str(self.session_message.uuid),
                str(self.session_unrelated.uuid),
            },
        )

    def test_search_matches_title(self):
        result = self._run(self.user, "pinecone")
        uuids = [entry["uuid"] for entry in result]
        self.assertIn(str(self.session_titled.uuid), uuids)

    def test_search_matches_message_content(self):
        result = self._run(self.user, "propagation")
        uuids = [entry["uuid"] for entry in result]
        self.assertEqual(uuids, [str(self.session_message.uuid)])

    def test_search_does_not_leak_across_users(self):
        result = self._run(self.user, "pinecone")
        uuids = {entry["uuid"] for entry in result}
        self.assertNotIn(str(self.other_session.uuid), uuids)

    def test_search_is_case_insensitive(self):
        upper = self._run(self.user, "PINECONE")
        lower = self._run(self.user, "pinecone")
        self.assertEqual(
            {e["uuid"] for e in upper}, {e["uuid"] for e in lower}
        )

    def test_match_snippet_present_for_message_hit(self):
        result = self._run(self.user, "propagation")
        self.assertEqual(len(result), 1)
        snippet = result[0].get("match_snippet")
        self.assertIsNotNone(snippet)
        self.assertIn("propagation", snippet.lower())

    def test_distinct_when_multiple_messages_match(self):
        # Two messages in the same session both match — the session
        # should only appear once.
        ChatMessageFactory(
            session=self.session_message,
            role="assistant",
            content="Sure, pinecone propagation works best when…",
        )
        result = self._run(self.user, "pinecone")
        uuids = [entry["uuid"] for entry in result]
        self.assertEqual(len(uuids), len(set(uuids)))
