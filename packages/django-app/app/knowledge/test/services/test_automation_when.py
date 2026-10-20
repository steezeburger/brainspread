"""Reactive `when::` evaluation (issue #206)."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from knowledge.services import automation_when
from knowledge.services.automation_spec import (
    WHEN_BECOMES_EMPTY,
    WHEN_BECOMES_NONEMPTY,
    WHEN_COUNT,
    WHEN_MATCHED_FOR,
    WhenSpec,
)

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestEvaluateCountBaseline(TestCase):
    """`becomes-empty` / `becomes-nonempty` / `count <op> N` edge
    detection against the previous run's matched count — the baseline IS
    the ledger, per the issue's worked-out design."""

    def test_becomes_empty_first_run_empty_does_not_fire(self):
        when = WhenSpec(kind=WHEN_BECOMES_EMPTY, raw="becomes-empty")
        outcome = automation_when.evaluate_count_baseline(when, 0, None)
        self.assertFalse(outcome.should_fire)
        self.assertEqual(outcome.reason, "first-run-empty")

    def test_becomes_empty_first_run_nonempty_does_not_fire(self):
        when = WhenSpec(kind=WHEN_BECOMES_EMPTY, raw="becomes-empty")
        outcome = automation_when.evaluate_count_baseline(when, 5, None)
        self.assertFalse(outcome.should_fire)
        self.assertEqual(outcome.reason, "first-run")

    def test_becomes_empty_fires_on_transition(self):
        when = WhenSpec(kind=WHEN_BECOMES_EMPTY, raw="becomes-empty")
        outcome = automation_when.evaluate_count_baseline(when, 0, 5)
        self.assertTrue(outcome.should_fire)
        self.assertEqual(outcome.reason, "transitioned")

    def test_becomes_empty_still_clear_does_not_refire(self):
        when = WhenSpec(kind=WHEN_BECOMES_EMPTY, raw="becomes-empty")
        outcome = automation_when.evaluate_count_baseline(when, 0, 0)
        self.assertFalse(outcome.should_fire)
        self.assertEqual(outcome.reason, "still-clear")

    def test_becomes_empty_still_in_progress_does_not_fire(self):
        when = WhenSpec(kind=WHEN_BECOMES_EMPTY, raw="becomes-empty")
        outcome = automation_when.evaluate_count_baseline(when, 3, 5)
        self.assertFalse(outcome.should_fire)
        self.assertEqual(outcome.reason, "still-in-progress")

    def test_becomes_nonempty_fires_on_transition(self):
        when = WhenSpec(kind=WHEN_BECOMES_NONEMPTY, raw="becomes-nonempty")
        outcome = automation_when.evaluate_count_baseline(when, 5, 0)
        self.assertTrue(outcome.should_fire)
        self.assertEqual(outcome.reason, "transitioned")

    def test_becomes_nonempty_still_satisfied_does_not_refire(self):
        when = WhenSpec(kind=WHEN_BECOMES_NONEMPTY, raw="becomes-nonempty")
        outcome = automation_when.evaluate_count_baseline(when, 5, 3)
        self.assertFalse(outcome.should_fire)
        self.assertEqual(outcome.reason, "still-satisfied")

    def test_becomes_nonempty_still_unsatisfied_does_not_fire(self):
        when = WhenSpec(kind=WHEN_BECOMES_NONEMPTY, raw="becomes-nonempty")
        outcome = automation_when.evaluate_count_baseline(when, 0, 0)
        self.assertFalse(outcome.should_fire)
        self.assertEqual(outcome.reason, "still-unsatisfied")

    def test_count_threshold_fires_on_crossing(self):
        when = WhenSpec(kind=WHEN_COUNT, raw="count > 5", op=">", threshold=5)
        outcome = automation_when.evaluate_count_baseline(when, 6, 5)
        self.assertTrue(outcome.should_fire)

    def test_count_threshold_still_satisfied_does_not_refire(self):
        when = WhenSpec(kind=WHEN_COUNT, raw="count > 5", op=">", threshold=5)
        outcome = automation_when.evaluate_count_baseline(when, 7, 6)
        self.assertFalse(outcome.should_fire)
        self.assertEqual(outcome.reason, "still-satisfied")

    def test_count_threshold_still_unsatisfied_does_not_fire(self):
        when = WhenSpec(kind=WHEN_COUNT, raw="count > 5", op=">", threshold=5)
        outcome = automation_when.evaluate_count_baseline(when, 4, 3)
        self.assertFalse(outcome.should_fire)
        self.assertEqual(outcome.reason, "still-unsatisfied")


class TestComputeFingerprint(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def test_no_watch_is_empty_fingerprint(self):
        block = BlockFactory(user=self.user, page=self.page)
        self.assertEqual(automation_when.compute_fingerprint(block, None), {})
        self.assertEqual(automation_when.compute_fingerprint(block, frozenset()), {})

    def test_due_token_reads_due_at(self):
        block = BlockFactory(user=self.user, page=self.page, due_at=None)
        fp = automation_when.compute_fingerprint(block, frozenset({"due"}))
        self.assertIsNone(fp["due"])

        block.due_at = timezone.now()
        fp = automation_when.compute_fingerprint(block, frozenset({"due"}))
        self.assertEqual(fp["due"], block.due_at.isoformat())

    def test_type_and_content_tokens(self):
        block = BlockFactory(
            user=self.user, page=self.page, block_type="doing", content="working on it"
        )
        fp = automation_when.compute_fingerprint(block, frozenset({"type", "content"}))
        self.assertEqual(fp["type"], "doing")
        self.assertEqual(fp["content"], "working on it")

    def test_tag_token_reflects_membership(self):
        tag_page = PageFactory(user=self.user, title="Priority", slug="priority")
        block = BlockFactory(user=self.user, page=self.page)
        fp = automation_when.compute_fingerprint(block, frozenset({"tag:priority"}))
        self.assertFalse(fp["tag:priority"])

        block.pages.add(tag_page)
        fp = automation_when.compute_fingerprint(block, frozenset({"tag:priority"}))
        self.assertTrue(fp["tag:priority"])

    def test_property_token_reads_properties_dict(self):
        block = BlockFactory(
            user=self.user, page=self.page, properties={"size": "large"}
        )
        fp = automation_when.compute_fingerprint(block, frozenset({"property:size"}))
        self.assertEqual(fp["property:size"], "large")


class TestSyncDwell(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def test_new_block_starts_dwell_clock_now_and_is_not_ready(self):
        block = BlockFactory(user=self.user, page=self.page)
        when = WhenSpec(
            kind=WHEN_MATCHED_FOR, raw="matched-for 2h", duration=timedelta(hours=2)
        )
        now = timezone.now()

        result = automation_when.sync_dwell(
            when=when, watch=None, blocks=[block], existing={}, now=now
        )

        self.assertEqual(result.ready_blocks, [])
        self.assertEqual(len(result.upserts), 1)
        uuid_str, first_matched_at, fingerprint = result.upserts[0]
        self.assertEqual(uuid_str, str(block.uuid))
        self.assertEqual(first_matched_at, now)
        self.assertEqual(fingerprint, {})
        self.assertEqual(result.stale_block_uuids, [])

    def test_block_dwelled_long_enough_is_ready(self):
        block = BlockFactory(user=self.user, page=self.page)
        when = WhenSpec(
            kind=WHEN_MATCHED_FOR, raw="matched-for 2h", duration=timedelta(hours=2)
        )
        now = timezone.now()
        started = now - timedelta(hours=3)

        class _Row:
            fingerprint = {}
            first_matched_at = started

        result = automation_when.sync_dwell(
            when=when,
            watch=None,
            blocks=[block],
            existing={str(block.uuid): _Row()},
            now=now,
        )

        self.assertEqual(result.ready_blocks, [block])
        self.assertEqual(result.upserts[0][1], started)

    def test_block_still_dwelling_is_not_ready(self):
        block = BlockFactory(user=self.user, page=self.page)
        when = WhenSpec(
            kind=WHEN_MATCHED_FOR, raw="matched-for 2h", duration=timedelta(hours=2)
        )
        now = timezone.now()
        started = now - timedelta(minutes=30)

        class _Row:
            fingerprint = {}
            first_matched_at = started

        result = automation_when.sync_dwell(
            when=when,
            watch=None,
            blocks=[block],
            existing={str(block.uuid): _Row()},
            now=now,
        )

        self.assertEqual(result.ready_blocks, [])

    def test_changed_fingerprint_resets_dwell_clock(self):
        block = BlockFactory(user=self.user, page=self.page, block_type="doing")
        when = WhenSpec(
            kind=WHEN_MATCHED_FOR, raw="matched-for 2h", duration=timedelta(hours=2)
        )
        now = timezone.now()
        started = now - timedelta(hours=3)

        class _Row:
            fingerprint = {"type": "todo"}  # different from block's current "doing"
            first_matched_at = started

        result = automation_when.sync_dwell(
            when=when,
            watch=frozenset({"type"}),
            blocks=[block],
            existing={str(block.uuid): _Row()},
            now=now,
        )

        # Fingerprint changed → treated as a fresh match, not ready yet.
        self.assertEqual(result.ready_blocks, [])
        self.assertEqual(result.upserts[0][1], now)

    def test_block_no_longer_matched_is_reported_stale(self):
        when = WhenSpec(
            kind=WHEN_MATCHED_FOR, raw="matched-for 2h", duration=timedelta(hours=2)
        )
        now = timezone.now()

        class _Row:
            fingerprint = {}
            first_matched_at = now - timedelta(hours=1)

        gone_uuid = "11111111-1111-1111-1111-111111111111"
        result = automation_when.sync_dwell(
            when=when, watch=None, blocks=[], existing={gone_uuid: _Row()}, now=now
        )

        self.assertEqual(result.stale_block_uuids, [gone_uuid])
        self.assertEqual(result.ready_blocks, [])
        self.assertEqual(result.upserts, [])
