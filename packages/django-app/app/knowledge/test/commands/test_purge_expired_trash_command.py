from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from knowledge.commands import PurgeExpiredTrashCommand
from knowledge.forms.purge_expired_trash_form import PurgeExpiredTrashForm
from knowledge.models import Block, Page

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestPurgeExpiredTrashCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def _run(self, retention_days=None, now=None):
        data = {"user": self.user.id}
        if retention_days is not None:
            data["retention_days"] = retention_days
        if now is not None:
            data["now"] = now
        form = PurgeExpiredTrashForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        return PurgeExpiredTrashCommand(form).execute()

    def test_purges_pages_past_the_retention_window(self):
        page = PageFactory(user=self.user)
        page.delete()
        old_deleted_at = timezone.now() - timedelta(days=45)
        Page.objects.filter(pk=page.pk).update(deleted_at=old_deleted_at)

        result = self._run(retention_days=30)

        self.assertEqual(result["pages_purged"], 1)
        self.assertFalse(Page.objects.filter(uuid=page.uuid).exists())

    def test_keeps_pages_within_the_retention_window(self):
        page = PageFactory(user=self.user)
        page.delete()

        result = self._run(retention_days=30)

        self.assertEqual(result["pages_purged"], 0)
        self.assertTrue(Page.objects.filter(uuid=page.uuid).exists())

    def test_keeps_active_pages_regardless_of_age(self):
        page = PageFactory(user=self.user)
        Page.objects.filter(pk=page.pk).update(
            modified_at=timezone.now() - timedelta(days=100)
        )

        result = self._run(retention_days=30)

        self.assertEqual(result["pages_purged"], 0)
        self.assertTrue(Page.objects.filter(uuid=page.uuid).exists())

    def test_purges_blocks_deleted_independently_past_the_window(self):
        page = PageFactory(user=self.user)
        block = BlockFactory(user=self.user, page=page)
        block.delete()
        old_deleted_at = timezone.now() - timedelta(days=45)
        Block.objects.filter(pk=block.pk).update(deleted_at=old_deleted_at)

        result = self._run(retention_days=30)

        self.assertEqual(result["blocks_purged"], 1)
        self.assertFalse(Block.objects.filter(uuid=block.uuid).exists())
        # The still-active page must survive.
        self.assertTrue(Page.objects.filter(uuid=page.uuid).exists())

    def test_purging_an_expired_page_also_purges_its_equally_aged_blocks(self):
        # Blocks soft-deleted alongside a page archive share its deleted_at,
        # so they age out (and get purged) on the block step by themselves.
        page = PageFactory(user=self.user)
        block = BlockFactory(user=self.user, page=page)
        page.delete()
        block.delete()
        old = timezone.now() - timedelta(days=45)
        Page.objects.filter(pk=page.pk).update(deleted_at=old)
        Block.objects.filter(pk=block.pk).update(deleted_at=old)

        result = self._run(retention_days=30)

        self.assertEqual(result["pages_purged"], 1)
        self.assertEqual(result["blocks_purged"], 1)
        self.assertFalse(Page.objects.filter(uuid=page.uuid).exists())
        self.assertFalse(Block.objects.filter(uuid=block.uuid).exists())

    def test_purging_an_expired_page_cascades_a_not_yet_aged_out_block(self):
        # A block that only became inactive via the page archive and
        # hasn't independently aged past the retention window yet rides
        # along in the page's hard-delete cascade rather than lingering.
        page = PageFactory(user=self.user)
        block = BlockFactory(user=self.user, page=page)
        page.delete()
        block.delete()
        Page.objects.filter(pk=page.pk).update(
            deleted_at=timezone.now() - timedelta(days=45)
        )
        # Block stays "fresh" — well within the retention window on its own.

        result = self._run(retention_days=30)

        self.assertEqual(result["pages_purged"], 1)
        self.assertEqual(result["blocks_purged"], 0)
        self.assertFalse(Page.objects.filter(uuid=page.uuid).exists())
        self.assertFalse(Block.objects.filter(uuid=block.uuid).exists())

    def test_default_retention_is_30_days(self):
        page = PageFactory(user=self.user)
        page.delete()
        Page.objects.filter(pk=page.pk).update(
            deleted_at=timezone.now() - timedelta(days=31)
        )

        result = self._run()

        self.assertEqual(result["pages_purged"], 1)
