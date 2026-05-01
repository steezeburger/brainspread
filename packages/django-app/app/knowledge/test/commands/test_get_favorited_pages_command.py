from django.test import TestCase

from knowledge.commands import GetFavoritedPagesCommand
from knowledge.forms import GetFavoritedPagesForm

from ..helpers import PageFactory, UserFactory


class TestGetFavoritedPagesCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.other_user = UserFactory()

        cls.fav_b = PageFactory(user=cls.user, title="Beta", favorited=True)
        cls.fav_a = PageFactory(user=cls.user, title="Alpha", favorited=True)
        cls.unfav = PageFactory(user=cls.user, title="Gamma", favorited=False)
        # Another user's favorite must never leak into the response.
        cls.other_fav = PageFactory(
            user=cls.other_user, title="Stranger", favorited=True
        )

    def _run(self, user):
        form = GetFavoritedPagesForm({"user": user.id})
        self.assertTrue(form.is_valid(), form.errors)
        return GetFavoritedPagesCommand(form).execute()

    def test_should_return_only_users_favorites_sorted_by_title(self):
        pages = self._run(self.user)
        self.assertEqual(
            [str(p.uuid) for p in pages],
            [str(self.fav_a.uuid), str(self.fav_b.uuid)],
        )

    def test_should_exclude_unfavorited_pages(self):
        pages = self._run(self.user)
        slugs = {p.slug for p in pages}
        self.assertNotIn(self.unfav.slug, slugs)

    def test_should_not_leak_across_users(self):
        pages = self._run(self.other_user)
        self.assertEqual([str(p.uuid) for p in pages], [str(self.other_fav.uuid)])

    def test_should_return_empty_list_when_none_favorited(self):
        empty_user = UserFactory()
        PageFactory(user=empty_user, title="Plain", favorited=False)
        pages = self._run(empty_user)
        self.assertEqual(pages, [])
