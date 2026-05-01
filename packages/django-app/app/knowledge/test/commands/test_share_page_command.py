from django.test import TestCase

from knowledge.commands import SharePageCommand
from knowledge.forms import SharePageForm

from ..helpers import PageFactory, UserFactory


class TestSharePageCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user, title="Trip Plans")

    def _share(self, mode: str):
        form = SharePageForm(
            {"user": self.user.id, "page": self.page.uuid, "share_mode": mode}
        )
        self.assertTrue(form.is_valid(), form.errors)
        return SharePageCommand(form).execute()

    def test_should_default_to_private_with_no_token(self):
        # Sanity check on the model defaults — sharing must be opt-in.
        self.assertEqual(self.page.share_mode, "private")
        self.assertFalse(self.page.share_token)
        self.assertFalse(self.page.is_publicly_viewable)

    def test_should_generate_share_token_when_set_to_link(self):
        page = self._share("link")
        self.assertEqual(page.share_mode, "link")
        self.assertTrue(page.share_token)
        # Tokens should be opaque, URL-safe, and reasonably long
        self.assertGreaterEqual(len(page.share_token), 16)
        self.assertTrue(page.is_publicly_viewable)

    def test_should_keep_token_stable_across_mode_toggles(self):
        # Matches Google Docs: an existing share link keeps working after a
        # private detour without forcing the sender to reissue the URL.
        page = self._share("link")
        original_token = page.share_token

        page = self._share("private")
        self.assertEqual(page.share_mode, "private")
        self.assertEqual(page.share_token, original_token)
        self.assertFalse(page.is_publicly_viewable)

        page = self._share("public")
        self.assertEqual(page.share_mode, "public")
        self.assertEqual(page.share_token, original_token)
        self.assertTrue(page.is_publicly_viewable)

    def test_should_reject_unknown_mode(self):
        form = SharePageForm(
            {
                "user": self.user.id,
                "page": self.page.uuid,
                "share_mode": "everyone",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("share_mode", form.errors)

    def test_should_reject_other_users_page(self):
        other_user = UserFactory()
        other_page = PageFactory(user=other_user, title="Their Notes")
        form = SharePageForm(
            {
                "user": self.user.id,
                "page": other_page.uuid,
                "share_mode": "link",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("page", form.errors)
