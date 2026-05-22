from django.core.exceptions import ValidationError
from django.test import TestCase

from ai_chat.commands import ReorderFavoritedChatSessionsCommand
from ai_chat.forms import ReorderFavoritedChatSessionsForm
from ai_chat.repositories import ChatSessionRepository
from ai_chat.test.helpers import ChatSessionFactory
from core.test.helpers import UserFactory


class TestReorderFavoritedChatSessionsCommand(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.a = ChatSessionFactory(
            user=self.user, title="alpha", is_favorited=True, favorite_position=0
        )
        self.b = ChatSessionFactory(
            user=self.user, title="bravo", is_favorited=True, favorite_position=1
        )
        self.c = ChatSessionFactory(
            user=self.user, title="charlie", is_favorited=True, favorite_position=2
        )

    def _run(self, *, session_uuids):
        form = ReorderFavoritedChatSessionsForm(
            {"user": self.user.id, "session_uuids": session_uuids}
        )
        self.assertTrue(form.is_valid(), form.errors)
        return ReorderFavoritedChatSessionsCommand(form).execute()

    def test_persists_full_explicit_ordering(self):
        self._run(session_uuids=[str(self.c.uuid), str(self.a.uuid), str(self.b.uuid)])
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.c.refresh_from_db()
        # New positions reflect the requested order, 0-indexed.
        self.assertEqual(self.c.favorite_position, 0)
        self.assertEqual(self.a.favorite_position, 1)
        self.assertEqual(self.b.favorite_position, 2)

    def test_partial_payload_keeps_omitted_favorites_at_end(self):
        # Caller lists only b → b ends up first, the omitted a and c
        # follow in their existing relative order so nothing silently
        # drops off the Pinned section.
        self._run(session_uuids=[str(self.b.uuid)])
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.c.refresh_from_db()
        self.assertEqual(self.b.favorite_position, 0)
        self.assertEqual(self.a.favorite_position, 1)
        self.assertEqual(self.c.favorite_position, 2)

    def test_rejects_uuid_not_in_user_favorites(self):
        # An unfavorited chat (even owned by the same user) isn't part
        # of the Pinned section; including its uuid in the payload is
        # a client-state bug we want to surface, not a silent no-op.
        unfavorited = ChatSessionFactory(user=self.user, is_favorited=False)
        form = ReorderFavoritedChatSessionsForm(
            {"user": self.user.id, "session_uuids": [str(unfavorited.uuid)]}
        )
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(ValidationError):
            ReorderFavoritedChatSessionsCommand(form).execute()

    def test_rejects_uuid_belonging_to_another_user(self):
        other = UserFactory()
        their_fav = ChatSessionFactory(user=other, is_favorited=True)
        form = ReorderFavoritedChatSessionsForm(
            {"user": self.user.id, "session_uuids": [str(their_fav.uuid)]}
        )
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(ValidationError):
            ReorderFavoritedChatSessionsCommand(form).execute()

    def test_form_rejects_duplicate_uuids(self):
        form = ReorderFavoritedChatSessionsForm(
            {
                "user": self.user.id,
                "session_uuids": [str(self.a.uuid), str(self.a.uuid)],
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("session_uuids", form.errors)


class TestFavoritePositionAssignedOnPin(TestCase):
    """set_favorited should append newly-favorited chats to the end
    of the Pinned section so we don't shuffle already-pinned rows."""

    def setUp(self):
        self.user = UserFactory()

    def test_first_favorite_gets_position_zero(self):
        s = ChatSessionFactory(user=self.user, is_favorited=False)
        ChatSessionRepository.set_favorited(
            uuid=str(s.uuid), user=self.user, is_favorited=True
        )
        s.refresh_from_db()
        self.assertEqual(s.favorite_position, 0)

    def test_subsequent_favorites_append_to_end(self):
        first = ChatSessionFactory(user=self.user, is_favorited=False)
        second = ChatSessionFactory(user=self.user, is_favorited=False)

        ChatSessionRepository.set_favorited(
            uuid=str(first.uuid), user=self.user, is_favorited=True
        )
        ChatSessionRepository.set_favorited(
            uuid=str(second.uuid), user=self.user, is_favorited=True
        )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.favorite_position, 0)
        self.assertEqual(second.favorite_position, 1)

    def test_unfavorite_leaves_remaining_positions_intact(self):
        # Pulling a chat out of the Pinned section shouldn't renumber
        # the others — favorite_position is only meaningful for
        # is_favorited rows, and stale numbers stay harmless until the
        # next reorder.
        a = ChatSessionFactory(user=self.user, is_favorited=True, favorite_position=0)
        b = ChatSessionFactory(user=self.user, is_favorited=True, favorite_position=1)
        ChatSessionRepository.set_favorited(
            uuid=str(a.uuid), user=self.user, is_favorited=False
        )
        b.refresh_from_db()
        self.assertEqual(b.favorite_position, 1)
