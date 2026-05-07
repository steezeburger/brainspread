from django.core.exceptions import ValidationError
from django.test import TestCase

from knowledge.commands import ReorderFavoritedPagesCommand, SetPageFavoritedCommand
from knowledge.forms import ReorderFavoritedPagesForm, SetPageFavoritedForm

from ..helpers import PageFactory, UserFactory


class TestReorderFavoritedPagesCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.other_user = UserFactory()

    def _favorite(self, user, **kwargs):
        page = PageFactory(user=user, **kwargs)
        form = SetPageFavoritedForm(
            {"user": user.id, "page": page.uuid, "favorited": True}
        )
        self.assertTrue(form.is_valid(), form.errors)
        SetPageFavoritedCommand(form).execute()
        page.refresh_from_db()
        return page

    def _reorder(self, user, page_uuids):
        form = ReorderFavoritedPagesForm({"user": user.id, "page_uuids": page_uuids})
        self.assertTrue(form.is_valid(), form.errors)
        return ReorderFavoritedPagesCommand(form).execute()

    def test_should_persist_new_order(self):
        a = self._favorite(self.user, title="Alpha")
        b = self._favorite(self.user, title="Beta")
        c = self._favorite(self.user, title="Gamma")

        result = self._reorder(self.user, [str(c.uuid), str(a.uuid), str(b.uuid)])
        self.assertEqual(
            [str(p.uuid) for p in result],
            [str(c.uuid), str(a.uuid), str(b.uuid)],
        )

    def test_newly_favorited_lands_at_bottom(self):
        a = self._favorite(self.user, title="Alpha")
        b = self._favorite(self.user, title="Beta")
        # b was favorited last, so it should land below a.
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertLess(a.favorite_position, b.favorite_position)

    def test_should_reject_pages_not_in_users_favorites(self):
        owned = self._favorite(self.user, title="Mine")
        stranger = self._favorite(self.other_user, title="Theirs")

        form = ReorderFavoritedPagesForm(
            {
                "user": self.user.id,
                "page_uuids": [str(owned.uuid), str(stranger.uuid)],
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(ValidationError):
            ReorderFavoritedPagesCommand(form).execute()

    def test_omitted_favorites_keep_position_relative_to_each_other(self):
        a = self._favorite(self.user, title="Alpha")
        b = self._favorite(self.user, title="Beta")
        c = self._favorite(self.user, title="Gamma")

        # Caller only sends one — the others should sit after it but in a
        # stable order, not be lost.
        result = self._reorder(self.user, [str(c.uuid)])
        self.assertEqual(result[0].uuid, c.uuid)
        remaining = {str(p.uuid) for p in result[1:]}
        self.assertEqual(remaining, {str(a.uuid), str(b.uuid)})

    def test_should_reject_duplicate_uuids_in_payload(self):
        a = self._favorite(self.user, title="Alpha")
        form = ReorderFavoritedPagesForm(
            {
                "user": self.user.id,
                "page_uuids": [str(a.uuid), str(a.uuid)],
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("page_uuids", form.errors)
