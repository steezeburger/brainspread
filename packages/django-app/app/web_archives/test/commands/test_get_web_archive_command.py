from django.test import TestCase

from web_archives.commands import GetWebArchiveCommand
from web_archives.forms import GetWebArchiveForm
from web_archives.models import WebArchive

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestGetWebArchiveCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def test_returns_none_when_no_archive_yet(self):
        block = BlockFactory(user=self.user, page=self.page)
        form = GetWebArchiveForm({"user": self.user.id, "block": block.uuid})
        self.assertTrue(form.is_valid(), form.errors)

        result = GetWebArchiveCommand(form).execute()
        self.assertIsNone(result)

    def test_returns_archive_when_present(self):
        block = BlockFactory(user=self.user, page=self.page)
        archive = WebArchive.objects.create(
            user=self.user,
            block=block,
            source_url="https://example.com/a",
            status="ready",
        )

        form = GetWebArchiveForm({"user": self.user.id, "block": block.uuid})
        self.assertTrue(form.is_valid())

        result = GetWebArchiveCommand(form).execute()
        self.assertEqual(result.pk, archive.pk)

    def test_does_not_leak_archives_across_users(self):
        other = UserFactory()
        other_page = PageFactory(user=other)
        other_block = BlockFactory(user=other, page=other_page)
        WebArchive.objects.create(
            user=other, block=other_block, source_url="https://example.com/b"
        )

        form = GetWebArchiveForm({"user": self.user.id, "block": other_block.uuid})
        self.assertFalse(form.is_valid())
