from django.test import TestCase

from knowledge.commands import SetPageFavoritedCommand
from knowledge.forms import SetPageFavoritedForm

from ..helpers import PageFactory, UserFactory


class TestSetPageFavoritedCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user, title="My Notes")

    def _set(self, favorited: bool):
        form = SetPageFavoritedForm(
            {
                "user": self.user.id,
                "page": self.page.uuid,
                "favorited": favorited,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        return SetPageFavoritedCommand(form).execute()

    def test_should_default_to_unfavorited(self):
        # Sanity check on the model default — favoriting must be opt-in.
        self.assertFalse(self.page.favorited)

    def test_should_set_favorited_true(self):
        page = self._set(True)
        self.assertTrue(page.favorited)
        page.refresh_from_db()
        self.assertTrue(page.favorited)

    def test_should_clear_favorited(self):
        self._set(True)
        page = self._set(False)
        self.assertFalse(page.favorited)
        page.refresh_from_db()
        self.assertFalse(page.favorited)

    def test_should_reject_other_users_page(self):
        other_user = UserFactory()
        other_page = PageFactory(user=other_user, title="Their Notes")
        form = SetPageFavoritedForm(
            {
                "user": self.user.id,
                "page": other_page.uuid,
                "favorited": True,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("page", form.errors)
