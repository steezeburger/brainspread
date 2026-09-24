from django.test import TestCase

from ai_chat.tools.notes_handlers import _archive_page, _restore_page
from core.llm_tools import ToolContext
from knowledge.repositories import PageRepository
from knowledge.test.helpers import PageFactory, UserFactory


class ArchiveRestorePageHandlerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def _ctx(self) -> ToolContext:
        return ToolContext(user=self.user, current_page_uuid=None)

    def test_archive_page_soft_deletes(self):
        page = PageFactory(user=self.user)

        result = _archive_page(self._ctx(), {"page_uuid": str(page.uuid)})

        self.assertTrue(result.get("archived"), result)
        self.assertFalse(PageRepository.get_queryset().filter(uuid=page.uuid).exists())

    def test_archive_page_requires_page_uuid(self):
        result = _archive_page(self._ctx(), {})
        self.assertIn("error", result)

    def test_archive_page_rejects_another_users_page(self):
        other = UserFactory()
        page = PageFactory(user=other)

        result = _archive_page(self._ctx(), {"page_uuid": str(page.uuid)})

        self.assertIn("error", result)
        self.assertTrue(PageRepository.get_queryset().filter(uuid=page.uuid).exists())

    def test_restore_page_undoes_archive_page(self):
        page = PageFactory(user=self.user)
        _archive_page(self._ctx(), {"page_uuid": str(page.uuid)})

        result = _restore_page(self._ctx(), {"page_uuid": str(page.uuid)})

        self.assertTrue(result.get("restored"), result)
        self.assertTrue(PageRepository.get_queryset().filter(uuid=page.uuid).exists())

    def test_restore_page_requires_page_uuid(self):
        result = _restore_page(self._ctx(), {})
        self.assertIn("error", result)

    def test_restore_page_errors_for_an_active_page(self):
        page = PageFactory(user=self.user)

        result = _restore_page(self._ctx(), {"page_uuid": str(page.uuid)})

        self.assertIn("error", result)
