from django.test import TestCase

from knowledge.commands import SetSavedViewArchivedCommand, SetSavedViewPinnedCommand
from knowledge.forms import SetSavedViewArchivedForm, SetSavedViewPinnedForm
from knowledge.repositories import SavedViewRepository

from ..helpers import UserFactory


class TestSetSavedViewArchivedCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.view = SavedViewRepository.create(
            user=cls.user,
            name="Yosemite prep",
            slug="yosemite-prep",
            filter_spec={"block_type": "todo"},
            sort=[],
        )

    def _set_archived(self, archived: bool):
        form = SetSavedViewArchivedForm(
            {
                "user": self.user.id,
                "view": self.view.uuid,
                "archived": archived,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        return SetSavedViewArchivedCommand(form).execute()

    def _set_pinned(self, pinned: bool):
        form = SetSavedViewPinnedForm(
            {
                "user": self.user.id,
                "view": self.view.uuid,
                "pinned": pinned,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        return SetSavedViewPinnedCommand(form).execute()

    def test_should_default_to_unarchived(self):
        self.assertFalse(self.view.archived)

    def test_should_archive_view(self):
        view = self._set_archived(True)
        self.assertTrue(view.archived)
        view.refresh_from_db()
        self.assertTrue(view.archived)

    def test_should_unarchive_view(self):
        self._set_archived(True)
        view = self._set_archived(False)
        self.assertFalse(view.archived)
        view.refresh_from_db()
        self.assertFalse(view.archived)

    def test_should_reject_other_users_view(self):
        other_user = UserFactory()
        other_view = SavedViewRepository.create(
            user=other_user,
            name="Theirs",
            slug="theirs",
            filter_spec={"block_type": "todo"},
            sort=[],
        )
        form = SetSavedViewArchivedForm(
            {
                "user": self.user.id,
                "view": other_view.uuid,
                "archived": True,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("view", form.errors)

    def test_archived_serializes_in_to_dict(self):
        self.assertFalse(self.view.to_dict()["archived"])
        view = self._set_archived(True)
        self.assertTrue(view.to_dict()["archived"])

    def test_archiving_keeps_pinned_flag_but_hides_from_pinned_list(self):
        self._set_pinned(True)
        view = self._set_archived(True)
        self.assertTrue(view.pinned)
        self.assertEqual(SavedViewRepository.list_pinned_for_user(self.user), [])

        # Unarchiving restores the pin without re-pinning.
        view = self._set_archived(False)
        self.assertTrue(view.pinned)
        pinned = SavedViewRepository.list_pinned_for_user(self.user)
        self.assertEqual([v.uuid for v in pinned], [view.uuid])

    def test_archived_views_stay_in_list_for_user(self):
        # The main list endpoint returns archived rows too — the client
        # splits them into the collapsed archived section.
        self._set_archived(True)
        views = SavedViewRepository.list_for_user(self.user)
        self.assertIn(self.view.uuid, [v.uuid for v in views])
