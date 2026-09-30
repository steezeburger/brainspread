from django.test import TestCase

from core.commands import UpdateHighlightHashtagsCommand
from core.forms import UpdateHighlightHashtagsForm
from core.test.helpers import UserFactory


class TestUpdateHighlightHashtagsCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def test_should_default_to_highlighting_hashtags(self):
        self.assertTrue(self.user.highlight_hashtags)

    def test_should_turn_hashtag_highlighting_off(self):
        form = UpdateHighlightHashtagsForm(
            {"user": self.user.id, "highlight_hashtags": False},
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = UpdateHighlightHashtagsCommand(form).execute()

        self.assertFalse(result.highlight_hashtags)
        self.user.refresh_from_db()
        self.assertFalse(self.user.highlight_hashtags)

    def test_should_turn_hashtag_highlighting_back_on(self):
        self.user.highlight_hashtags = False
        self.user.save(update_fields=["highlight_hashtags"])

        form = UpdateHighlightHashtagsForm(
            {"user": self.user.id, "highlight_hashtags": True}
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = UpdateHighlightHashtagsCommand(form).execute()

        self.assertTrue(result.highlight_hashtags)
        self.user.refresh_from_db()
        self.assertTrue(self.user.highlight_hashtags)

    def test_should_treat_a_missing_value_as_off(self):
        """BooleanField(required=False) is how an unchecked box arrives —
        absent means False, not "leave it alone"."""
        self.user.highlight_hashtags = True
        self.user.save(update_fields=["highlight_hashtags"])

        form = UpdateHighlightHashtagsForm({"user": self.user.id})
        self.assertTrue(form.is_valid(), form.errors)

        result = UpdateHighlightHashtagsCommand(form).execute()

        self.assertFalse(result.highlight_hashtags)

    def test_should_reject_an_unknown_user(self):
        form = UpdateHighlightHashtagsForm({"user": 999999, "highlight_hashtags": True})

        self.assertFalse(form.is_valid())
        self.assertIn("user", form.errors)
