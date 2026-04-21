from django.test import TestCase

from knowledge.commands import CreatePageCommand
from knowledge.forms import CreatePageForm

from ..helpers import UserFactory


class TestCreatePageCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def test_should_create_page_with_default_page_type(self):
        form = CreatePageForm(
            {
                "user": self.user.id,
                "title": "My Page",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        page = CreatePageCommand(form).execute()

        self.assertEqual(page.page_type, "page")
        self.assertEqual(page.title, "My Page")
        self.assertEqual(page.slug, "my-page")

    def test_should_create_whiteboard_page_when_page_type_is_whiteboard(self):
        form = CreatePageForm(
            {
                "user": self.user.id,
                "title": "Brain Dump Board",
                "page_type": "whiteboard",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        page = CreatePageCommand(form).execute()

        self.assertEqual(page.page_type, "whiteboard")
        self.assertEqual(page.title, "Brain Dump Board")
        self.assertEqual(page.slug, "brain-dump-board")

    def test_should_reject_invalid_page_type(self):
        form = CreatePageForm(
            {
                "user": self.user.id,
                "title": "Bad Page",
                "page_type": "not-a-real-type",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("page_type", form.errors)
