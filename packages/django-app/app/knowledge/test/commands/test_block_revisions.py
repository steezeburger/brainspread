"""Revision recording across the write chokepoints that touch tracked
fields (content, block_type, properties, due_at, due_at_has_time,
completed_at), plus ListBlockRevisionsCommand and
RestoreBlockRevisionCommand (issue #234).
"""

from django.test import TestCase
from django.utils import timezone

from knowledge.commands import (
    ListBlockRevisionsCommand,
    RestoreBlockRevisionCommand,
    ScheduleBlockCommand,
    SetBlockCompletedAtCommand,
    SetBlockTypeCommand,
    SnoozeBlockCommand,
    UpdateBlockCommand,
)
from knowledge.forms import (
    ListBlockRevisionsForm,
    RestoreBlockRevisionForm,
    ScheduleBlockForm,
    SetBlockCompletedAtForm,
    SetBlockTypeForm,
    SnoozeBlockForm,
    UpdateBlockForm,
)
from knowledge.models import Block, BlockRevision

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestUpdateBlockCommandRecordsRevisions(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(timezone="UTC")
        cls.page = PageFactory(user=cls.user)

    def _update(self, block: Block, **data) -> Block:
        form = UpdateBlockForm({"user": self.user.id, "block": str(block.uuid), **data})
        self.assertTrue(form.is_valid(), form.errors)
        return UpdateBlockCommand(form).execute()

    def test_content_edit_records_a_revision_of_the_old_content(self):
        block = BlockFactory(user=self.user, page=self.page, content="buy milk")

        self._update(block, content="")

        revisions = list(block.revisions.all())
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0].content, "buy milk")
        self.assertEqual(revisions[0].source, BlockRevision.SOURCE_USER)

    def test_indent_only_save_does_not_record_a_revision(self):
        # Indent/move saves resubmit the same content — order/parent
        # aren't tracked fields, so no revision should be written.
        parent = BlockFactory(user=self.user, page=self.page, content="parent")
        block = BlockFactory(user=self.user, page=self.page, content="child")

        self._update(block, content="child", parent=str(parent.uuid), order=0)

        self.assertEqual(block.revisions.count(), 0)

    def test_explicit_source_is_recorded(self):
        block = BlockFactory(user=self.user, page=self.page, content="x")

        self._update(block, content="y", source=BlockRevision.SOURCE_ASSISTANT)

        revision = block.revisions.get()
        self.assertEqual(revision.source, BlockRevision.SOURCE_ASSISTANT)

    def test_explicit_block_type_change_records_its_own_revision(self):
        block = BlockFactory(
            user=self.user, page=self.page, content="x", block_type="bullet"
        )

        self._update(block, block_type="todo")

        revision = block.revisions.get()
        self.assertEqual(revision.block_type, "bullet")


class TestSetBlockTypeCommandRecordsRevisions(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(timezone="UTC")
        cls.page = PageFactory(user=cls.user)

    def test_records_previous_type_and_completed_at(self):
        block = BlockFactory(
            user=self.user, page=self.page, content="TODO ship it", block_type="todo"
        )
        form = SetBlockTypeForm(
            {"user": self.user.id, "block": str(block.uuid), "block_type": "done"}
        )
        self.assertTrue(form.is_valid(), form.errors)

        SetBlockTypeCommand(form).execute()

        revision = block.revisions.get()
        self.assertEqual(revision.block_type, "todo")
        self.assertIsNone(revision.completed_at)

    def test_noop_transition_records_nothing(self):
        block = BlockFactory(
            user=self.user, page=self.page, content="TODO ship it", block_type="todo"
        )
        form = SetBlockTypeForm(
            {"user": self.user.id, "block": str(block.uuid), "block_type": "todo"}
        )
        self.assertTrue(form.is_valid(), form.errors)

        SetBlockTypeCommand(form).execute()

        self.assertEqual(block.revisions.count(), 0)


class TestSetBlockCompletedAtCommandRecordsRevisions(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(timezone="UTC")
        cls.page = PageFactory(user=cls.user)

    def test_records_previous_completed_at(self):
        original = timezone.now() - timezone.timedelta(days=1)
        block = BlockFactory(
            user=self.user,
            page=self.page,
            content="DONE x",
            block_type="done",
            completed_at=original,
        )
        new_value = timezone.now().isoformat()
        form = SetBlockCompletedAtForm(
            {"user": self.user.id, "block": str(block.uuid), "completed_at": new_value}
        )
        self.assertTrue(form.is_valid(), form.errors)

        SetBlockCompletedAtCommand(form).execute()

        revision = block.revisions.get()
        self.assertEqual(revision.completed_at, original)


class TestScheduleAndSnoozeCommandsRecordRevisions(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(timezone="UTC")
        cls.page = PageFactory(user=cls.user)

    def test_schedule_block_records_previous_due_at(self):
        block = BlockFactory(user=self.user, page=self.page, content="x")
        form = ScheduleBlockForm(
            {"user": self.user.id, "block": str(block.uuid), "due_date": "2030-01-01"}
        )
        self.assertTrue(form.is_valid(), form.errors)

        ScheduleBlockCommand(form).execute()

        revision = block.revisions.get()
        self.assertIsNone(revision.due_at)

    def test_snooze_block_records_previous_due_at(self):
        block = BlockFactory(user=self.user, page=self.page, content="x")
        schedule_form = ScheduleBlockForm(
            {"user": self.user.id, "block": str(block.uuid), "due_date": "2030-01-01"}
        )
        self.assertTrue(schedule_form.is_valid(), schedule_form.errors)
        ScheduleBlockCommand(schedule_form).execute()
        block.refresh_from_db()
        original_due_at = block.due_at

        snooze_form = SnoozeBlockForm(
            {"user": self.user.id, "block": str(block.uuid), "days": 3}
        )
        self.assertTrue(snooze_form.is_valid(), snooze_form.errors)
        SnoozeBlockCommand(snooze_form).execute()

        revisions = list(block.revisions.order_by("created_at"))
        self.assertEqual(len(revisions), 2)
        self.assertEqual(revisions[1].due_at, original_due_at)


class TestListBlockRevisionsCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(timezone="UTC")
        cls.page = PageFactory(user=cls.user)

    def test_lists_newest_first(self):
        block = BlockFactory(user=self.user, page=self.page, content="v3")
        BlockRevision.objects.create(block=block, content="v1", block_type="bullet")
        BlockRevision.objects.create(block=block, content="v2", block_type="bullet")

        form = ListBlockRevisionsForm({"user": self.user.id, "block": str(block.uuid)})
        self.assertTrue(form.is_valid(), form.errors)
        result = ListBlockRevisionsCommand(form).execute()

        self.assertEqual([r["content"] for r in result], ["v2", "v1"])

    def test_rejects_block_from_another_user(self):
        other = UserFactory()
        block = BlockFactory(user=other, page=PageFactory(user=other), content="x")

        form = ListBlockRevisionsForm({"user": self.user.id, "block": str(block.uuid)})
        self.assertFalse(form.is_valid())


class TestRestoreBlockRevisionCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(timezone="UTC")
        cls.page = PageFactory(user=cls.user)

    def _restore(self, block: Block, revision: BlockRevision, **extra) -> Block:
        form = RestoreBlockRevisionForm(
            {
                "user": self.user.id,
                "block": str(block.uuid),
                "revision": str(revision.uuid),
                **extra,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        return RestoreBlockRevisionCommand(form).execute()

    def test_restore_writes_the_revisions_values_back_onto_the_block(self):
        block = BlockFactory(
            user=self.user, page=self.page, content="cleared", block_type="bullet"
        )
        revision = BlockRevision.objects.create(
            block=block, content="buy milk", block_type="bullet"
        )

        restored = self._restore(block, revision)

        self.assertEqual(restored.content, "buy milk")

    def test_restore_is_itself_recorded_as_a_new_revision(self):
        block = BlockFactory(
            user=self.user, page=self.page, content="cleared", block_type="bullet"
        )
        revision = BlockRevision.objects.create(
            block=block, content="buy milk", block_type="bullet"
        )

        self._restore(block, revision)

        revisions = list(block.revisions.order_by("created_at"))
        # The revision we restored from, plus a new one capturing what
        # was live (the cleared content) right before the restore.
        self.assertEqual(len(revisions), 2)
        self.assertEqual(revisions[0].uuid, revision.uuid)
        self.assertEqual(revisions[1].content, "cleared")

    def test_restore_of_a_restore_undoes_it(self):
        block = BlockFactory(
            user=self.user, page=self.page, content="cleared", block_type="bullet"
        )
        original_revision = BlockRevision.objects.create(
            block=block, content="buy milk", block_type="bullet"
        )

        self._restore(block, original_revision)
        # The restore above just created a revision holding "cleared" —
        # restoring that undoes the restore.
        cleared_revision = block.revisions.exclude(uuid=original_revision.uuid).get()
        restored_again = self._restore(block, cleared_revision)

        self.assertEqual(restored_again.content, "cleared")

    def test_rejects_a_revision_belonging_to_a_different_block(self):
        block = BlockFactory(user=self.user, page=self.page, content="x")
        other_block = BlockFactory(user=self.user, page=self.page, content="y")
        other_revision = BlockRevision.objects.create(
            block=other_block, content="z", block_type="bullet"
        )

        form = RestoreBlockRevisionForm(
            {
                "user": self.user.id,
                "block": str(block.uuid),
                "revision": str(other_revision.uuid),
            }
        )

        self.assertFalse(form.is_valid())

    def test_rejects_block_from_another_user(self):
        other = UserFactory()
        block = BlockFactory(user=other, page=PageFactory(user=other), content="x")
        revision = BlockRevision.objects.create(
            block=block, content="y", block_type="bullet"
        )

        form = RestoreBlockRevisionForm(
            {
                "user": self.user.id,
                "block": str(block.uuid),
                "revision": str(revision.uuid),
            }
        )

        self.assertFalse(form.is_valid())
