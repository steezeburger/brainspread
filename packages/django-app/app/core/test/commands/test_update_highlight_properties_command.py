from django.test import TestCase

from core.commands import UpdateHighlightPropertiesCommand
from core.forms import UpdateHighlightPropertiesForm
from core.test.helpers import UserFactory


class TestUpdateHighlightPropertiesCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def test_should_default_to_highlighting_properties(self):
        self.assertTrue(self.user.highlight_properties)

    def test_should_turn_property_highlighting_off(self):
        form = UpdateHighlightPropertiesForm(
            {"user": self.user.id, "highlight_properties": False},
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = UpdateHighlightPropertiesCommand(form).execute()

        self.assertFalse(result.highlight_properties)
        self.user.refresh_from_db()
        self.assertFalse(self.user.highlight_properties)

    def test_should_turn_property_highlighting_back_on(self):
        self.user.highlight_properties = False
        self.user.save(update_fields=["highlight_properties"])

        form = UpdateHighlightPropertiesForm(
            {"user": self.user.id, "highlight_properties": True}
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = UpdateHighlightPropertiesCommand(form).execute()

        self.assertTrue(result.highlight_properties)
        self.user.refresh_from_db()
        self.assertTrue(self.user.highlight_properties)

    def test_should_treat_a_missing_value_as_off(self):
        """BooleanField(required=False) is how an unchecked box arrives —
        absent means False, not "leave it alone"."""
        self.user.highlight_properties = True
        self.user.save(update_fields=["highlight_properties"])

        form = UpdateHighlightPropertiesForm({"user": self.user.id})
        self.assertTrue(form.is_valid(), form.errors)

        result = UpdateHighlightPropertiesCommand(form).execute()

        self.assertFalse(result.highlight_properties)

    def test_should_reject_an_unknown_user(self):
        form = UpdateHighlightPropertiesForm(
            {"user": 999999, "highlight_properties": True}
        )

        self.assertFalse(form.is_valid())
        self.assertIn("user", form.errors)
