from django.test import TestCase

from web_archives.commands import SoftDeleteWebArchivesForBlocksCommand
from web_archives.forms import SoftDeleteWebArchivesForBlocksForm
from web_archives.models import WebArchive

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestSoftDeleteWebArchivesForBlocksCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def test_soft_deletes_archives_for_the_given_blocks(self):
        block = BlockFactory(user=self.user, page=self.page)
        archive = WebArchive.objects.create(
            user=self.user, block=block, source_url="https://example.com/a"
        )

        form = SoftDeleteWebArchivesForBlocksForm(
            {"user": self.user.id, "block_uuids": [str(block.uuid)]}
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = SoftDeleteWebArchivesForBlocksCommand(form).execute()

        self.assertEqual(result, 1)
        archive.refresh_from_db()
        self.assertFalse(archive.is_active)

    def test_rejects_an_empty_block_list(self):
        form = SoftDeleteWebArchivesForBlocksForm(
            {"user": self.user.id, "block_uuids": []}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("block_uuids", form.errors)
