from django.test import TestCase

from core.commands import UpdateHighlightPropertyValuesCommand
from core.forms import UpdateHighlightPropertyValuesForm
from core.test.helpers import UserFactory


class TestUpdateHighlightPropertyValuesCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def test_should_default_to_highlighting_property_values(self):
        self.assertTrue(self.user.highlight_property_values)

    def test_should_turn_property_value_highlighting_off(self):
        form = UpdateHighlightPropertyValuesForm(
            {"user": self.user.id, "highlight_property_values": False},
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = UpdateHighlightPropertyValuesCommand(form).execute()

        self.assertFalse(result.highlight_property_values)
        self.user.refresh_from_db()
        self.assertFalse(self.user.highlight_property_values)

    def test_should_turn_property_value_highlighting_back_on(self):
        self.user.highlight_property_values = False
        self.user.save(update_fields=["highlight_property_values"])

        form = UpdateHighlightPropertyValuesForm(
            {"user": self.user.id, "highlight_property_values": True}
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = UpdateHighlightPropertyValuesCommand(form).execute()

        self.assertTrue(result.highlight_property_values)
        self.user.refresh_from_db()
        self.assertTrue(self.user.highlight_property_values)

    def test_should_treat_a_missing_value_as_off(self):
        """BooleanField(required=False) is how an unchecked box arrives —
        absent means False, not "leave it alone"."""
        self.user.highlight_property_values = True
        self.user.save(update_fields=["highlight_property_values"])

        form = UpdateHighlightPropertyValuesForm({"user": self.user.id})
        self.assertTrue(form.is_valid(), form.errors)

        result = UpdateHighlightPropertyValuesCommand(form).execute()

        self.assertFalse(result.highlight_property_values)

    def test_should_reject_an_unknown_user(self):
        form = UpdateHighlightPropertyValuesForm(
            {"user": 999999, "highlight_property_values": True}
        )

        self.assertFalse(form.is_valid())
        self.assertIn("user", form.errors)
