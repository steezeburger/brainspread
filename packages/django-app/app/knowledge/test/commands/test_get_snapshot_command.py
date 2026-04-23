from django.test import TestCase

from knowledge.commands import GetSnapshotCommand
from knowledge.forms import GetSnapshotForm
from knowledge.models import Snapshot

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestGetSnapshotCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def test_returns_none_when_no_snapshot_yet(self):
        block = BlockFactory(user=self.user, page=self.page)
        form = GetSnapshotForm({"user": self.user.id, "block": block.uuid})
        self.assertTrue(form.is_valid(), form.errors)

        result = GetSnapshotCommand(form).execute()
        self.assertIsNone(result)

    def test_returns_snapshot_when_present(self):
        block = BlockFactory(user=self.user, page=self.page)
        snapshot = Snapshot.objects.create(
            user=self.user,
            block=block,
            source_url="https://example.com/a",
            status="ready",
        )

        form = GetSnapshotForm({"user": self.user.id, "block": block.uuid})
        self.assertTrue(form.is_valid())

        result = GetSnapshotCommand(form).execute()
        self.assertEqual(result.pk, snapshot.pk)

    def test_does_not_leak_snapshots_across_users(self):
        other = UserFactory()
        other_page = PageFactory(user=other)
        other_block = BlockFactory(user=other, page=other_page)
        Snapshot.objects.create(
            user=other, block=other_block, source_url="https://example.com/b"
        )

        form = GetSnapshotForm({"user": self.user.id, "block": other_block.uuid})
        self.assertFalse(form.is_valid())
