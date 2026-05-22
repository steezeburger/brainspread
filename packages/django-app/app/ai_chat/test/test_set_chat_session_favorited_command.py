from django.test import TestCase

from ai_chat.commands import SetChatSessionFavoritedCommand
from ai_chat.forms import SetChatSessionFavoritedForm
from ai_chat.test.helpers import ChatSessionFactory
from core.test.helpers import UserFactory


class TestSetChatSessionFavoritedCommand(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.session = ChatSessionFactory(user=self.user, is_favorited=False)

    def _run(self, *, user, session_uuid, is_favorited):
        form = SetChatSessionFavoritedForm(
            {
                "user": user.id,
                "session_id": str(session_uuid),
                "is_favorited": is_favorited,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        return SetChatSessionFavoritedCommand(form).execute()

    def test_marks_session_as_favorited(self):
        result = self._run(
            user=self.user, session_uuid=self.session.uuid, is_favorited=True
        )
        self.assertEqual(result["uuid"], str(self.session.uuid))
        self.assertTrue(result["is_favorited"])
        self.session.refresh_from_db()
        self.assertTrue(self.session.is_favorited)

    def test_unfavorite_round_trip(self):
        # favorite first, then unfavorite — both should persist
        self._run(user=self.user, session_uuid=self.session.uuid, is_favorited=True)
        result = self._run(
            user=self.user, session_uuid=self.session.uuid, is_favorited=False
        )
        self.assertFalse(result["is_favorited"])
        self.session.refresh_from_db()
        self.assertFalse(self.session.is_favorited)

    def test_rejects_session_owned_by_other_user(self):
        other = UserFactory()
        form = SetChatSessionFavoritedForm(
            {
                "user": other.id,
                "session_id": str(self.session.uuid),
                "is_favorited": True,
            }
        )
        # The form's _ChatSessionLookupMixin scopes the lookup by user
        # so cross-user requests fail validation rather than reaching
        # the repository.
        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)

    def test_rejects_unknown_session(self):
        form = SetChatSessionFavoritedForm(
            {
                "user": self.user.id,
                "session_id": "00000000-0000-0000-0000-000000000000",
                "is_favorited": True,
            }
        )
        self.assertFalse(form.is_valid())
