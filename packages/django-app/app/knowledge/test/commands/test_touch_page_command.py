from django.core.exceptions import ValidationError
from django.test import TestCase

from knowledge.commands import TouchPageCommand
from knowledge.forms import TouchPageForm

from ..helpers import PageFactory, UserFactory


class TestTouchPageCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def test_should_advance_modified_at(self):
        original_modified_at = self.page.modified_at

        form = TouchPageForm({"user": self.user.id, "page": str(self.page.uuid)})
        self.assertTrue(form.is_valid(), form.errors)
        TouchPageCommand(form).execute()

        self.page.refresh_from_db()
        self.assertGreater(self.page.modified_at, original_modified_at)

    def test_should_reject_page_owned_by_another_user(self):
        other_user = UserFactory()
        form = TouchPageForm({"user": other_user.id, "page": str(self.page.uuid)})
        self.assertFalse(form.is_valid())

    def test_should_raise_when_form_invalid(self):
        # Missing page entirely.
        form = TouchPageForm({"user": self.user.id})
        with self.assertRaises(ValidationError):
            TouchPageCommand(form).execute()
