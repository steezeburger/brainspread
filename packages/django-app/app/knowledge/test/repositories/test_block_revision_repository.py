from django.test import TestCase
from django.utils import timezone

from knowledge.models import BlockRevision
from knowledge.repositories import BlockRevisionRepository

from ..helpers import BlockFactory, UserFactory


class TestBlockRevisionRepositorySnapshotAndRecord(TestCase):
    """snapshot()/record_if_changed() are the explicit call-and-response
    pair every tracked-field write path uses instead of a signal or a
    save() override."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def test_record_if_changed_noop_when_nothing_tracked_changed(self):
        block = BlockFactory(user=self.user, content="hello", block_type="bullet")
        previous = BlockRevisionRepository.snapshot(block)

        # Mutate an untracked field only (order) — mirrors an indent/move
        # save that sends unchanged content.
        block.order = 5
        block.save(update_fields=["order"])

        result = BlockRevisionRepository.record_if_changed(
            block, previous, BlockRevision.SOURCE_USER
        )

        self.assertIsNone(result)
        self.assertEqual(BlockRevision.objects.filter(block=block).count(), 0)

    def test_record_if_changed_writes_the_previous_content(self):
        block = BlockFactory(user=self.user, content="original", block_type="bullet")
        previous = BlockRevisionRepository.snapshot(block)

        block.content = ""
        block.save(update_fields=["content"])

        revision = BlockRevisionRepository.record_if_changed(
            block, previous, BlockRevision.SOURCE_USER
        )

        self.assertIsNotNone(revision)
        # The revision holds the state being superseded (the old content),
        # not the new one — that's what lets a user scroll history and see
        # what a block said right before it was cleared.
        self.assertEqual(revision.content, "original")
        self.assertEqual(revision.block_type, "bullet")
        self.assertEqual(revision.source, BlockRevision.SOURCE_USER)
        self.assertEqual(revision.block_id, block.id)

    def test_record_if_changed_detects_block_type_change(self):
        block = BlockFactory(user=self.user, content="x", block_type="todo")
        previous = BlockRevisionRepository.snapshot(block)

        block.block_type = "done"
        block.save(update_fields=["block_type"])

        revision = BlockRevisionRepository.record_if_changed(
            block, previous, BlockRevision.SOURCE_AUTOMATION
        )

        self.assertIsNotNone(revision)
        self.assertEqual(revision.block_type, "todo")
        self.assertEqual(revision.source, BlockRevision.SOURCE_AUTOMATION)

    def test_record_if_changed_detects_properties_change(self):
        block = BlockFactory(
            user=self.user, content="x", properties={"priority": "low"}
        )
        previous = BlockRevisionRepository.snapshot(block)

        block.properties = {"priority": "high"}
        block.save(update_fields=["properties"])

        revision = BlockRevisionRepository.record_if_changed(
            block, previous, BlockRevision.SOURCE_USER
        )

        self.assertIsNotNone(revision)
        self.assertEqual(revision.properties, {"priority": "low"})

    def test_record_if_changed_noop_when_properties_unchanged(self):
        block = BlockFactory(
            user=self.user, content="x", properties={"priority": "low"}
        )
        previous = BlockRevisionRepository.snapshot(block)

        # Re-save with an identical properties dict (a fresh object, same
        # value) — must not be treated as a change.
        block.properties = {"priority": "low"}
        block.save(update_fields=["properties"])

        result = BlockRevisionRepository.record_if_changed(
            block, previous, BlockRevision.SOURCE_USER
        )

        self.assertIsNone(result)

    def test_list_for_block_orders_newest_first(self):
        block = BlockFactory(user=self.user, content="x")
        older = BlockRevision.objects.create(
            block=block, content="v1", block_type="bullet"
        )
        older.created_at = timezone.now() - timezone.timedelta(days=1)
        older.save(update_fields=["created_at"])
        newer = BlockRevision.objects.create(
            block=block, content="v2", block_type="bullet"
        )

        result = list(BlockRevisionRepository.list_for_block(block))

        self.assertEqual([r.id for r in result], [newer.id, older.id])

    def test_list_for_block_scoped_to_the_block(self):
        block = BlockFactory(user=self.user, content="x")
        other_block = BlockFactory(user=self.user, content="y")
        BlockRevision.objects.create(
            block=other_block, content="v1", block_type="bullet"
        )

        result = list(BlockRevisionRepository.list_for_block(block))

        self.assertEqual(result, [])
