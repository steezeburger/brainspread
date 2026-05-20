from django.test import TestCase

from ai_chat.commands.send_message_command import (
    AUTO_TITLE_MAX_LEN,
    SendMessageCommand,
)
from ai_chat.repositories import ChatSessionRepository
from ai_chat.test.helpers import ChatSessionFactory
from core.test.helpers import UserFactory


class TestDeriveAutoTitle(TestCase):
    """Pure-function tests for the auto-title formatter."""

    def test_short_message_returned_as_is(self):
        self.assertEqual(
            SendMessageCommand._derive_auto_title("What is a pinecone?"),
            "What is a pinecone?",
        )

    def test_collapses_newlines_and_whitespace(self):
        self.assertEqual(
            SendMessageCommand._derive_auto_title("hello\n\n  world\t!"),
            "hello world !",
        )

    def test_empty_message_returns_empty(self):
        # Image-only turns send an empty caption; auto-titling shouldn't
        # overwrite the existing (blank) title with another blank.
        self.assertEqual(SendMessageCommand._derive_auto_title(""), "")
        self.assertEqual(SendMessageCommand._derive_auto_title("   "), "")

    def test_truncates_long_message_with_ellipsis(self):
        # Anything past AUTO_TITLE_MAX_LEN gets clipped to a word
        # boundary and ends with the ellipsis character.
        long_msg = " ".join(["word"] * 50)
        title = SendMessageCommand._derive_auto_title(long_msg)
        self.assertLessEqual(len(title), AUTO_TITLE_MAX_LEN)
        self.assertTrue(title.endswith("…"))
        # Word boundary respected — no half-word before the ellipsis.
        body = title.rstrip("…").rstrip()
        self.assertFalse(body.endswith("wor"))

    def test_truncation_falls_back_when_no_word_boundary(self):
        # A single super-long token has nowhere to split — we still
        # truncate to the max length rather than blow past it.
        title = SendMessageCommand._derive_auto_title("x" * 200)
        self.assertLessEqual(len(title), AUTO_TITLE_MAX_LEN)
        self.assertTrue(title.endswith("…"))


class TestSetTitleIfBlank(TestCase):
    """ChatSessionRepository.set_title_if_blank should be idempotent."""

    def setUp(self):
        self.user = UserFactory()

    def test_sets_title_on_blank_session(self):
        session = ChatSessionFactory(user=self.user, title="")
        ChatSessionRepository.set_title_if_blank(session, "Recipe brainstorm")
        session.refresh_from_db()
        self.assertEqual(session.title, "Recipe brainstorm")

    def test_no_op_on_already_titled_session(self):
        # Manual renames must survive subsequent turns — set_title_if_blank
        # is what each SendMessage call invokes, so a user-curated title
        # has to win against the auto-derived one.
        session = ChatSessionFactory(user=self.user, title="My pinned chat")
        ChatSessionRepository.set_title_if_blank(session, "Different label")
        session.refresh_from_db()
        self.assertEqual(session.title, "My pinned chat")

    def test_no_op_on_empty_derived_title(self):
        # An image-only first turn produces an empty derived title.
        # The session keeps its (still blank) title rather than getting
        # an "" written into the column.
        session = ChatSessionFactory(user=self.user, title="")
        ChatSessionRepository.set_title_if_blank(session, "")
        session.refresh_from_db()
        self.assertEqual(session.title, "")

    def test_truncates_to_field_max_length(self):
        # The repo is the last line of defense — even if someone hands
        # it a string longer than the column, it must fit.
        session = ChatSessionFactory(user=self.user, title="")
        max_len = session._meta.get_field("title").max_length
        ChatSessionRepository.set_title_if_blank(session, "x" * (max_len + 50))
        session.refresh_from_db()
        self.assertEqual(len(session.title), max_len)
