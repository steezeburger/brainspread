from django.test import TestCase

from ai_chat.commands import UpdateChatSessionTitleCommand
from ai_chat.forms import UpdateChatSessionTitleForm
from ai_chat.test.helpers import ChatSessionFactory
from core.test.helpers import UserFactory


class TestUpdateChatSessionTitleCommand(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.session = ChatSessionFactory(user=self.user, title="old title")

    def _run(self, *, user, session_uuid, title):
        form = UpdateChatSessionTitleForm(
            {
                "user": user.id,
                "session_id": str(session_uuid),
                "title": title,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        return UpdateChatSessionTitleCommand(form).execute()

    def test_updates_title_for_owner(self):
        result = self._run(
            user=self.user,
            session_uuid=self.session.uuid,
            title="Recipe brainstorm",
        )
        self.assertEqual(result["title"], "Recipe brainstorm")
        self.session.refresh_from_db()
        self.assertEqual(self.session.title, "Recipe brainstorm")

    def test_trims_whitespace(self):
        self._run(
            user=self.user,
            session_uuid=self.session.uuid,
            title="   padded   ",
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.title, "padded")

    def test_rejects_blank_title(self):
        form = UpdateChatSessionTitleForm(
            {
                "user": self.user.id,
                "session_id": str(self.session.uuid),
                "title": "   ",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("title", form.errors)

    def test_rejects_session_owned_by_other_user(self):
        other = UserFactory()
        form = UpdateChatSessionTitleForm(
            {
                "user": other.id,
                "session_id": str(self.session.uuid),
                "title": "Hostile rename",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)
