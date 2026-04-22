from django.test import TestCase

from knowledge.commands import UpdatePageCommand
from knowledge.forms import UpdatePageForm

from ..helpers import PageFactory, UserFactory


class TestUpdatePageCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(
            user=cls.user, title="Original", whiteboard_snapshot="old"
        )

    def test_should_update_snapshot_without_touching_title_when_title_omitted(self):
        # Whiteboard saves only send `whiteboard_snapshot` in the payload.
        # The form must not reject this as "Title cannot be empty".
        form = UpdatePageForm(
            {
                "user": self.user.id,
                "page": self.page.uuid,
                "whiteboard_snapshot": '{"snapshot": true}',
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        page = UpdatePageCommand(form).execute()
        self.assertEqual(page.title, "Original")
        self.assertEqual(page.whiteboard_snapshot, '{"snapshot": true}')

    def test_should_reject_explicitly_empty_title(self):
        form = UpdatePageForm(
            {
                "user": self.user.id,
                "page": self.page.uuid,
                "title": "   ",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("title", form.errors)

    def test_should_update_title_when_provided(self):
        form = UpdatePageForm(
            {
                "user": self.user.id,
                "page": self.page.uuid,
                "title": "New Title",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        page = UpdatePageCommand(form).execute()
        self.assertEqual(page.title, "New Title")
        self.assertEqual(page.slug, "new-title")
