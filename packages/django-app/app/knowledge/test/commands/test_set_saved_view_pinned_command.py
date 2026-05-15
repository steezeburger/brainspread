from django.test import TestCase

from knowledge.commands import SetSavedViewPinnedCommand
from knowledge.forms import SetSavedViewPinnedForm
from knowledge.repositories import SavedViewRepository

from ..helpers import UserFactory


class TestSetSavedViewPinnedCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.view = SavedViewRepository.create(
            user=cls.user,
            name="My todos",
            slug="my-todos",
            filter_spec={"block_type": "todo"},
            sort=[],
        )

    def _set(self, pinned: bool):
        form = SetSavedViewPinnedForm(
            {
                "user": self.user.id,
                "view": self.view.uuid,
                "pinned": pinned,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        return SetSavedViewPinnedCommand(form).execute()

    def test_should_default_to_unpinned(self):
        self.assertFalse(self.view.pinned)

    def test_should_pin_view(self):
        view = self._set(True)
        self.assertTrue(view.pinned)
        view.refresh_from_db()
        self.assertTrue(view.pinned)

    def test_should_unpin_view(self):
        self._set(True)
        view = self._set(False)
        self.assertFalse(view.pinned)
        view.refresh_from_db()
        self.assertFalse(view.pinned)

    def test_should_reject_other_users_view(self):
        other_user = UserFactory()
        other_view = SavedViewRepository.create(
            user=other_user,
            name="Theirs",
            slug="theirs",
            filter_spec={"block_type": "todo"},
            sort=[],
        )
        form = SetSavedViewPinnedForm(
            {
                "user": self.user.id,
                "view": other_view.uuid,
                "pinned": True,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("view", form.errors)

    def test_list_pinned_for_user_returns_only_pinned(self):
        other_view = SavedViewRepository.create(
            user=self.user,
            name="Other",
            slug="other",
            filter_spec={"block_type": "todo"},
            sort=[],
        )
        self._set(True)
        pinned = SavedViewRepository.list_pinned_for_user(self.user)
        self.assertEqual([v.uuid for v in pinned], [self.view.uuid])

        # Pin the other one and verify the list expands.
        form = SetSavedViewPinnedForm(
            {
                "user": self.user.id,
                "view": other_view.uuid,
                "pinned": True,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        SetSavedViewPinnedCommand(form).execute()
        pinned = SavedViewRepository.list_pinned_for_user(self.user)
        self.assertEqual(
            sorted(v.uuid for v in pinned),
            sorted([self.view.uuid, other_view.uuid]),
        )
