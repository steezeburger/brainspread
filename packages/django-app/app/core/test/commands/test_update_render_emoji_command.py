from django.test import TestCase

from core.commands import UpdateRenderEmojiCommand
from core.forms import UpdateRenderEmojiForm
from core.test.helpers import UserFactory


class TestUpdateRenderEmojiCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def test_should_default_to_rendering_emoji(self):
        self.assertTrue(self.user.render_emoji)

    def test_should_turn_emoji_rendering_off(self):
        form = UpdateRenderEmojiForm(
            {"user": self.user.id, "render_emoji": False},
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = UpdateRenderEmojiCommand(form).execute()

        self.assertFalse(result.render_emoji)
        self.user.refresh_from_db()
        self.assertFalse(self.user.render_emoji)

    def test_should_turn_emoji_rendering_back_on(self):
        self.user.render_emoji = False
        self.user.save(update_fields=["render_emoji"])

        form = UpdateRenderEmojiForm({"user": self.user.id, "render_emoji": True})
        self.assertTrue(form.is_valid(), form.errors)

        result = UpdateRenderEmojiCommand(form).execute()

        self.assertTrue(result.render_emoji)
        self.user.refresh_from_db()
        self.assertTrue(self.user.render_emoji)

    def test_should_treat_a_missing_value_as_off(self):
        """BooleanField(required=False) is how an unchecked box arrives —
        absent means False, not "leave it alone"."""
        self.user.render_emoji = True
        self.user.save(update_fields=["render_emoji"])

        form = UpdateRenderEmojiForm({"user": self.user.id})
        self.assertTrue(form.is_valid(), form.errors)

        result = UpdateRenderEmojiCommand(form).execute()

        self.assertFalse(result.render_emoji)

    def test_should_reject_an_unknown_user(self):
        form = UpdateRenderEmojiForm({"user": 999999, "render_emoji": True})

        self.assertFalse(form.is_valid())
        self.assertIn("user", form.errors)
