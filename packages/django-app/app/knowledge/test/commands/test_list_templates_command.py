from django.test import TestCase

from knowledge.commands import ListTemplatesCommand
from knowledge.forms import ListTemplatesForm

from ..helpers import PageFactory, UserFactory


class TestListTemplatesCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.other_user = UserFactory()

    def test_returns_only_user_templates_alphabetical(self):
        PageFactory(
            user=self.user, title="Workout", slug="workout-tpl", page_type="template"
        )
        PageFactory(
            user=self.user,
            title="Packing list",
            slug="packing-tpl",
            page_type="template",
        )
        PageFactory(user=self.user, title="Notes", slug="notes")
        # Other user's template should not leak through.
        PageFactory(
            user=self.other_user,
            title="Aaa",
            slug="aaa-tpl",
            page_type="template",
        )

        form = ListTemplatesForm({"user": self.user.id})
        self.assertTrue(form.is_valid(), form.errors)
        result = ListTemplatesCommand(form).execute()
        titles = [p.title for p in result]
        self.assertEqual(titles, ["Packing list", "Workout"])

    def test_returns_empty_list_when_no_templates(self):
        form = ListTemplatesForm({"user": self.user.id})
        self.assertTrue(form.is_valid())
        self.assertEqual(ListTemplatesCommand(form).execute(), [])
