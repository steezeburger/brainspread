from django.test import TestCase

from web_archives.models import WebArchive
from web_archives.repositories import WebArchiveRepository

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestSoftDeleteForBlocks(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def test_soft_deletes_every_archive_in_one_query(self):
        block_a = BlockFactory(user=self.user, page=self.page)
        block_b = BlockFactory(user=self.user, page=self.page)
        # No archive at all — must not error, just contribute nothing.
        block_c = BlockFactory(user=self.user, page=self.page)
        archive_a = WebArchive.objects.create(
            user=self.user, block=block_a, source_url="https://example.com/a"
        )
        archive_b = WebArchive.objects.create(
            user=self.user, block=block_b, source_url="https://example.com/b"
        )

        with self.assertNumQueries(1):
            count = WebArchiveRepository.soft_delete_for_blocks(
                [str(block_a.uuid), str(block_b.uuid), str(block_c.uuid)], self.user
            )

        self.assertEqual(count, 2)
        archive_a.refresh_from_db()
        archive_b.refresh_from_db()
        self.assertFalse(archive_a.is_active)
        self.assertIsNotNone(archive_a.deleted_at)
        self.assertFalse(archive_b.is_active)

    def test_does_not_touch_another_users_archive(self):
        other = UserFactory()
        other_page = PageFactory(user=other)
        other_block = BlockFactory(user=other, page=other_page)
        other_archive = WebArchive.objects.create(
            user=other, block=other_block, source_url="https://example.com/mine"
        )

        count = WebArchiveRepository.soft_delete_for_blocks(
            [str(other_block.uuid)], self.user
        )

        self.assertEqual(count, 0)
        other_archive.refresh_from_db()
        self.assertTrue(other_archive.is_active)

    def test_is_a_noop_for_an_empty_result_set(self):
        count = WebArchiveRepository.soft_delete_for_blocks([], self.user)
        self.assertEqual(count, 0)
