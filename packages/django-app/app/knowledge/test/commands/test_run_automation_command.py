import uuid as uuid_lib
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from knowledge.commands import RunAutomationCommand
from knowledge.forms.run_automation_form import RunAutomationForm
from knowledge.models import AutomationRun, Block, Reminder
from knowledge.repositories import AutomationRunRepository, SavedViewRepository
from knowledge.services.discord_webhook import DiscordDeliveryResult
from knowledge.services.due_dates import start_of_local_day

from ..helpers import BlockFactory, PageFactory, UserFactory

TODOS_FILTER = {"block_type": {"in": ["todo"]}}


class TestRunAutomationCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def _view(self, slug="todos"):
        return SavedViewRepository.create(
            user=self.user,
            name="Todos",
            slug=slug,
            filter_spec=TODOS_FILTER,
            sort=[],
        )

    def _automation(self, **props):
        page = PageFactory(
            user=self.user,
            title="Automations",
            slug=f"automations-{uuid_lib.uuid4().hex[:8]}",
        )
        return BlockFactory(
            user=self.user,
            page=page,
            content="My automation #automation",
            properties=props,
        )

    def _run(self, automation_block, trigger="manual"):
        form = RunAutomationForm(
            {
                "user": self.user,
                "automation_block": automation_block.uuid,
                "trigger": trigger,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        return RunAutomationCommand(form).execute()

    def test_command_action_runs_over_query_results_and_records_success(self):
        self._view()
        source = PageFactory(user=self.user, title="Notes", slug="notes")
        target = BlockFactory(
            user=self.user, page=source, block_type="todo", content="TODO ship it"
        )
        automation = self._automation(
            trigger="manual",
            query="view:todos",
            action="move_to_daily today",
            allow="move_to_daily",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        self.assertEqual(result["result"]["matched"], 1)
        self.assertEqual(result["result"]["affected"], 1)

        target.refresh_from_db()
        self.assertEqual(target.page.page_type, "daily")

        run = AutomationRun.objects.get(uuid=result["uuid"])
        self.assertEqual(run.status, AutomationRun.STATUS_SUCCEEDED)
        self.assertEqual(str(run.automation_block_uuid), str(automation.uuid))
        self.assertIsNotNone(run.finished_at)

    def test_set_type_action_changes_matched_block_type(self):
        self._view()
        source = PageFactory(user=self.user, title="Notes", slug="notes")
        target = BlockFactory(
            user=self.user, page=source, block_type="todo", content="TODO ship it"
        )
        automation = self._automation(
            trigger="manual",
            query="view:todos",
            action="set_type done",
            allow="set_type",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        target.refresh_from_db()
        self.assertEqual(target.block_type, "done")
        self.assertIsNotNone(target.completed_at)

    def test_disabled_automation_is_skipped_for_ambient_triggers(self):
        self._view()
        source = PageFactory(user=self.user, title="Notes", slug="notes")
        target = BlockFactory(
            user=self.user, page=source, block_type="todo", content="TODO ship it"
        )
        automation = self._automation(
            trigger="schedule daily 6:00",
            query="view:todos",
            action="move_to_daily today",
            allow="move_to_daily",
            enabled="false",
        )

        result = self._run(automation, trigger="schedule")

        self.assertEqual(result["status"], AutomationRun.STATUS_SKIPPED)
        target.refresh_from_db()
        self.assertEqual(target.page, source)

    def test_disabled_automation_still_runs_manually(self):
        # enabled:: false pauses ambient firing; an explicit manual run is
        # deliberate intent and goes through (the UI confirms beforehand).
        self._view()
        source = PageFactory(user=self.user, title="Notes", slug="notes")
        target = BlockFactory(
            user=self.user, page=source, block_type="todo", content="TODO ship it"
        )
        automation = self._automation(
            trigger="schedule daily 6:00",
            query="view:todos",
            action="set_type done",
            enabled="false",
        )

        result = self._run(automation, trigger="manual")

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        target.refresh_from_db()
        self.assertEqual(target.block_type, "done")

    def test_pre_claimed_run_is_finished_not_duplicated(self):
        # The scheduler's claim-then-execute path: a RUNNING run created at
        # claim time is completed by the command, not replaced.
        self._view()
        automation = self._automation(
            trigger="manual",
            query="view:todos",
            action="set_type done",
        )
        claim = AutomationRunRepository.create(
            user=self.user,
            automation_block_uuid=str(automation.uuid),
            trigger=AutomationRun.TRIGGER_SCHEDULE,
            status=AutomationRun.STATUS_RUNNING,
        )

        form = RunAutomationForm(
            {
                "user": self.user,
                "automation_block": automation.uuid,
                "run": str(claim.uuid),
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        result = RunAutomationCommand(form).execute()

        self.assertEqual(result["uuid"], str(claim.uuid))
        self.assertEqual(
            AutomationRun.objects.filter(automation_block_uuid=automation.uuid).count(),
            1,
        )
        claim.refresh_from_db()
        self.assertEqual(claim.status, AutomationRun.STATUS_SUCCEEDED)

    def test_run_for_wrong_automation_is_rejected(self):
        self._view()
        automation = self._automation(
            trigger="manual", query="view:todos", action="set_type done"
        )
        other = self._automation(
            trigger="manual", query="view:todos", action="set_type done"
        )
        claim = AutomationRunRepository.create(
            user=self.user,
            automation_block_uuid=str(other.uuid),
            trigger=AutomationRun.TRIGGER_SCHEDULE,
            status=AutomationRun.STATUS_RUNNING,
        )

        form = RunAutomationForm(
            {
                "user": self.user,
                "automation_block": automation.uuid,
                "run": str(claim.uuid),
            }
        )
        self.assertFalse(form.is_valid())

    def test_omitted_allow_implies_declared_verb(self):
        # No allow:: line at all — the action line is the authorization.
        self._view()
        source = PageFactory(user=self.user, title="Notes", slug="notes")
        target = BlockFactory(
            user=self.user, page=source, block_type="todo", content="TODO ship it"
        )
        automation = self._automation(
            trigger="manual",
            query="view:todos",
            action="set_type done",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        target.refresh_from_db()
        self.assertEqual(target.block_type, "done")

    def test_action_not_in_allow_list_fails(self):
        self._view()
        source = PageFactory(user=self.user, title="Notes", slug="notes")
        target = BlockFactory(
            user=self.user, page=source, block_type="todo", content="TODO ship it"
        )
        automation = self._automation(
            trigger="manual",
            query="view:todos",
            action="move_to_daily today",
            allow="",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("allow", result["last_error"])
        target.refresh_from_db()
        self.assertEqual(target.page, source)

    def test_parse_failure_records_failed_run(self):
        automation = self._automation(trigger="manual", query="view:todos")

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("action", result["last_error"])

    def test_missing_saved_view_fails(self):
        source = PageFactory(user=self.user, title="Notes", slug="notes")
        BlockFactory(user=self.user, page=source, block_type="todo", content="TODO x")
        automation = self._automation(
            trigger="manual",
            query="view:nonexistent",
            action="move_to_daily today",
            allow="move_to_daily",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("nonexistent", result["last_error"])

    def test_matched_parent_and_child_keep_hierarchy(self):
        # Both parent and child match the query; the child must ride along
        # with the parent, not get re-moved and detached (review finding).
        self._view()
        source = PageFactory(user=self.user, title="Notes", slug="notes")
        parent = BlockFactory(
            user=self.user, page=source, block_type="todo", content="TODO parent"
        )
        child = BlockFactory(
            user=self.user,
            page=source,
            parent=parent,
            block_type="todo",
            content="TODO child",
        )
        automation = self._automation(
            trigger="manual",
            query="view:todos",
            action="move_to_daily today",
            allow="move_to_daily",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        parent.refresh_from_db()
        child.refresh_from_db()
        self.assertEqual(parent.page.page_type, "daily")
        self.assertEqual(child.page, parent.page)
        self.assertEqual(child.parent, parent)

    def test_result_reports_truncation_when_query_exceeds_cap(self):
        self._view()
        source = PageFactory(user=self.user, title="Notes", slug="notes")
        for i in range(3):
            BlockFactory(
                user=self.user, page=source, block_type="todo", content=f"TODO {i}"
            )
        automation = self._automation(
            trigger="manual",
            query="view:todos",
            action="set_type done",
            allow="set_type",
        )

        with patch("knowledge.commands.run_automation_command.MAX_ACTION_BLOCKS", 2):
            result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        self.assertEqual(result["result"]["matched"], 2)
        self.assertTrue(result["result"]["truncated"])

    def test_unexpected_exception_fails_the_run_instead_of_stranding_it(self):
        # Any exception outside the action phase must still land the run in
        # FAILED with finished_at set — never stuck in RUNNING (review
        # finding).
        self._view()
        automation = self._automation(
            trigger="manual",
            query="view:todos",
            action="move_to_daily today",
            allow="move_to_daily",
        )

        with patch(
            "knowledge.commands.run_automation_command.resolve_and_run_view",
            side_effect=RuntimeError("db went away"),
        ):
            result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("unexpected error", result["last_error"])
        run = AutomationRun.objects.get(uuid=result["uuid"])
        self.assertEqual(run.status, AutomationRun.STATUS_FAILED)
        self.assertIsNotNone(run.finished_at)

    def test_move_to_page_by_title_slug_and_wiki_ref(self):
        target = PageFactory(user=self.user, title="Grocery List", slug="groceries")
        source = PageFactory(user=self.user, title="Notes", slug="notes-mtp")

        for ref, marker in (
            ('"Grocery List"', "by title"),
            ("groceries", "by slug"),
            ('"[[Grocery List]]"', "wiki sugar"),
        ):
            block = BlockFactory(
                user=self.user,
                page=source,
                block_type="todo",
                content=f"TODO buy things {marker}",
            )
            automation = self._automation(
                trigger="manual",
                query=f'content:"{marker}"',
                action=f"move_to_page {ref}",
            )

            result = self._run(automation)

            self.assertEqual(
                result["status"], AutomationRun.STATUS_SUCCEEDED, msg=marker
            )
            block.refresh_from_db()
            self.assertEqual(block.page, target, msg=marker)

    def test_move_to_page_preserves_hierarchy(self):
        target = PageFactory(user=self.user, title="Archive", slug="archive")
        source = PageFactory(user=self.user, title="Notes", slug="notes-mtp2")
        parent = BlockFactory(
            user=self.user, page=source, block_type="todo", content="TODO parent"
        )
        child = BlockFactory(
            user=self.user,
            page=source,
            parent=parent,
            block_type="todo",
            content="TODO child",
        )
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action='move_to_page "Archive"',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        parent.refresh_from_db()
        child.refresh_from_db()
        self.assertEqual(parent.page, target)
        self.assertEqual(child.page, target)
        self.assertEqual(child.parent, parent)

    def test_move_to_page_creates_missing_target_and_rejects_templates(self):
        PageFactory(user=self.user, title="Pack", slug="pack-tpl", page_type="template")
        source = PageFactory(user=self.user, title="Notes", slug="notes-mtp3")
        block = BlockFactory(
            user=self.user, page=source, block_type="todo", content="TODO x"
        )

        missing = self._automation(
            trigger="manual", query="type:todo", action='move_to_page "nope"'
        )
        result = self._run(missing)
        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        block.refresh_from_db()
        self.assertEqual(block.page.title, "nope")

        into_template = self._automation(
            trigger="manual", query="type:todo", action='move_to_page "Pack"'
        )
        result = self._run(into_template)
        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("template", result["last_error"])

    def test_inline_query_runs_end_to_end(self):
        source = PageFactory(user=self.user, title="Notes", slug="notes-inline")
        todo = BlockFactory(
            user=self.user, page=source, block_type="todo", content="TODO inline"
        )
        bullet = BlockFactory(
            user=self.user, page=source, block_type="bullet", content="just a note"
        )
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action="set_type done",
            allow="set_type",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        todo.refresh_from_db()
        bullet.refresh_from_db()
        self.assertEqual(todo.block_type, "done")
        self.assertEqual(bullet.block_type, "bullet")

    def test_start_when_due_flips_timed_overdue_todo_to_doing(self):
        # The motivating "Start when due" automation (#automation /
        # `trigger:: schedule every 5m`): a todo whose due date-TIME has
        # arrived flips to doing within one tick. An all-day todo due
        # today must NOT match — its due_at sits at local midnight, so
        # only the explicit due_has_time:true predicate keeps it out.
        source = PageFactory(user=self.user, title="Notes", slug="notes-due-now")
        now = timezone.now()
        timed_past = BlockFactory(
            user=self.user,
            page=source,
            block_type="todo",
            content="TODO standup",
            due_at=now - timedelta(minutes=10),
            due_at_has_time=True,
        )
        all_day_today = BlockFactory(
            user=self.user,
            page=source,
            block_type="todo",
            content="TODO groceries",
            due_at=start_of_local_day(self.user.today(), self.user.tz()),
            due_at_has_time=False,
        )
        timed_future = BlockFactory(
            user=self.user,
            page=source,
            block_type="todo",
            content="TODO review",
            due_at=now + timedelta(hours=1),
            due_at_has_time=True,
        )
        automation = self._automation(
            trigger="schedule every 5m",
            query="type:todo and due <= now and due_has_time:true",
            action="set_type doing",
        )

        result = self._run(automation, trigger="schedule")

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        self.assertEqual(result["result"]["matched"], 1)

        timed_past.refresh_from_db()
        all_day_today.refresh_from_db()
        timed_future.refresh_from_db()
        self.assertEqual(timed_past.block_type, "doing")
        self.assertIsNone(timed_past.completed_at)
        self.assertEqual(all_day_today.block_type, "todo")
        self.assertEqual(timed_future.block_type, "todo")

    def test_bulk_action_counts_only_top_blocks_as_affected(self):
        # A matched child riding along with its matched parent counts the
        # parent as the moved unit; matched=2 but affected=1.
        self._view()
        source = PageFactory(user=self.user, title="Notes", slug="notes")
        parent = BlockFactory(
            user=self.user, page=source, block_type="todo", content="TODO parent"
        )
        BlockFactory(
            user=self.user,
            page=source,
            parent=parent,
            block_type="todo",
            content="TODO child",
        )
        automation = self._automation(
            trigger="manual",
            query="view:todos",
            action="move_to_daily today",
            allow="move_to_daily",
        )

        result = self._run(automation)

        self.assertEqual(result["result"]["matched"], 2)
        self.assertEqual(result["result"]["affected"], 1)


class TestSmallVerbActions(TestCase):
    """The data-model verbs added on #199: tag / untag / set_due /
    set_property / create_block. All integration-tested through
    RunAutomationCommand so allow:: defaulting and result recording are
    exercised alongside each handler."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def _automation(self, **props):
        page = PageFactory(
            user=self.user,
            title="Automations",
            slug=f"automations-{uuid_lib.uuid4().hex[:8]}",
        )
        return BlockFactory(
            user=self.user,
            page=page,
            content="My automation #automation",
            properties=props,
        )

    def _run(self, automation_block, trigger="manual"):
        form = RunAutomationForm(
            {
                "user": self.user,
                "automation_block": automation_block.uuid,
                "trigger": trigger,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        return RunAutomationCommand(form).execute()

    def _todo(self, content="TODO ship it", **kwargs):
        page = kwargs.pop(
            "page",
            PageFactory(user=self.user, slug=f"notes-{uuid_lib.uuid4().hex[:8]}"),
        )
        return BlockFactory(
            user=self.user, page=page, block_type="todo", content=content, **kwargs
        )

    # -- tag / untag --------------------------------------------------------

    def test_tag_action_adds_page_tag_to_matches(self):
        tag_page = PageFactory(
            user=self.user, title="Needs Review", slug="needs-review"
        )
        target = self._todo()
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action="tag needs-review",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        self.assertEqual(result["result"]["affected"], 1)
        self.assertIn(tag_page, target.pages.all())

    def test_untag_own_query_tag_is_self_stopping(self):
        sticky = PageFactory(user=self.user, title="Sticky", slug="sticky")
        target = self._todo()
        target.pages.add(sticky)
        automation = self._automation(
            trigger="manual",
            query="tag:sticky",
            action="untag sticky",
        )

        first = self._run(automation)
        self.assertEqual(first["status"], AutomationRun.STATUS_SUCCEEDED)
        self.assertEqual(first["result"]["affected"], 1)
        self.assertNotIn(sticky, target.pages.all())

        second = self._run(automation)
        self.assertEqual(second["result"]["matched"], 0)

    def test_tag_rejects_hashtag_args_with_guidance(self):
        PageFactory(user=self.user, title="Sticky", slug="sticky")
        self._todo()
        automation = self._automation(
            trigger="manual", query="type:todo", action="tag #sticky"
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("automation block itself", result["last_error"])

    def test_tag_creates_missing_tag_page(self):
        target = self._todo()
        automation = self._automation(
            trigger="manual", query="type:todo", action="tag no-such-tag"
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        self.assertIn("no-such-tag", target.get_tag_names())

    # -- set_due ------------------------------------------------------------

    def test_set_due_sets_all_day_due_date(self):
        target = self._todo()
        automation = self._automation(
            trigger="manual", query="type:todo", action="set_due tomorrow"
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        target.refresh_from_db()
        self.assertIsNotNone(target.due_at)
        self.assertFalse(target.due_at_has_time)

    def test_set_due_none_clears_due_date(self):
        target = self._todo()
        set_automation = self._automation(
            trigger="manual", query="type:todo", action="set_due today"
        )
        self._run(set_automation)
        target.refresh_from_db()
        self.assertIsNotNone(target.due_at)

        clear_automation = self._automation(
            trigger="manual", query="type:todo", action="set_due none"
        )
        result = self._run(clear_automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        target.refresh_from_db()
        self.assertIsNone(target.due_at)

    def test_set_due_bad_token_fails(self):
        self._todo()
        automation = self._automation(
            trigger="manual", query="type:todo", action="set_due banana"
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("banana", result["last_error"])

    # -- set_property -------------------------------------------------------

    def test_set_property_appends_content_line_and_syncs(self):
        target = self._todo(content="Buy milk")
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action="set_property priority high",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        target.refresh_from_db()
        self.assertIn("priority:: high", target.content)
        self.assertEqual(target.properties.get("priority"), "high")

    def test_set_property_replaces_existing_line_without_duplicating(self):
        target = self._todo(content="Buy milk\npriority:: low")
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action='set_property priority "very high"',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        target.refresh_from_db()
        self.assertEqual(target.content.count("priority::"), 1)
        self.assertEqual(target.properties.get("priority"), "very high")

    def test_set_property_bad_key_fails(self):
        self._todo()
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action='set_property "bad key" value',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("bad property key", result["last_error"])

    # -- create_block -------------------------------------------------------

    def test_create_block_on_daily_date_token(self):
        automation = self._automation(
            trigger="manual",
            action='create_block "drink water" on today as todo',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        self.assertEqual(result["result"]["affected"], 1)
        created = Block.objects.get(user=self.user, content="drink water")
        self.assertEqual(created.block_type, "todo")
        self.assertEqual(created.page.page_type, "daily")

    def test_create_block_on_named_page(self):
        inbox = PageFactory(user=self.user, title="Inbox", slug="inbox")
        automation = self._automation(
            trigger="manual",
            action='create_block "captured thought" on Inbox',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        created = Block.objects.get(user=self.user, content="captured thought")
        self.assertEqual(created.page, inbox)
        self.assertEqual(created.block_type, "bullet")

    def test_create_block_requires_explicit_target(self):
        automation = self._automation(trigger="manual", action='create_block "orphan"')

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("explicit", result["last_error"])

    def test_create_block_rejects_unknown_type(self):
        automation = self._automation(
            trigger="manual", action='create_block "x" on today as banana'
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("banana", result["last_error"])

    # -- content-durable tagging & create_block clauses ---------------------

    def test_tag_writes_hashtag_into_content(self):
        PageFactory(user=self.user, title="Needs Review", slug="needs-review")
        target = self._todo(content="TODO ship it")
        automation = self._automation(
            trigger="manual", query="type:todo", action="tag needs-review"
        )

        self._run(automation)

        target.refresh_from_db()
        self.assertIn("#needs-review", target.content)

    def test_tag_is_idempotent_on_rerun(self):
        PageFactory(user=self.user, title="Needs Review", slug="needs-review")
        target = self._todo(content="TODO ship it")
        automation = self._automation(
            trigger="manual", query="type:todo", action="tag needs-review"
        )

        self._run(automation)
        second = self._run(automation)

        self.assertEqual(second["result"]["affected"], 0)
        target.refresh_from_db()
        self.assertEqual(target.content.count("#needs-review"), 1)

    def test_untag_strips_content_hashtag(self):
        sticky = PageFactory(user=self.user, title="Sticky", slug="sticky")
        target = self._todo(content="TODO ship it #sticky")
        target.pages.add(sticky)
        automation = self._automation(
            trigger="manual", query="tag:sticky", action="untag sticky"
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        target.refresh_from_db()
        self.assertNotIn("#sticky", target.content)
        self.assertNotIn(sticky, target.pages.all())

    def test_create_block_tagged_and_with_clauses(self):
        groceries = PageFactory(user=self.user, title="Groceries", slug="groceries")
        automation = self._automation(
            trigger="manual",
            action='create_block "buy milk" on today as todo '
            'tagged groceries with priority=high status="in review"',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        created = Block.objects.get(user=self.user, content__startswith="buy milk")
        self.assertIn("#groceries", created.content)
        self.assertIn(groceries, created.pages.all())
        self.assertEqual(created.properties.get("priority"), "high")
        self.assertEqual(created.properties.get("status"), "in review")
        self.assertEqual(created.block_type, "todo")

    def test_create_block_rejects_bare_hashtag_in_content(self):
        automation = self._automation(
            trigger="manual",
            action='create_block "buy milk #groceries" on today',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("tagged", result["last_error"])

    def test_create_block_rejects_property_syntax_in_content(self):
        automation = self._automation(
            trigger="manual",
            action='create_block "buy milk priority:: high" on today',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("with key=value", result["last_error"])

    def test_create_block_rejects_bad_with_pair(self):
        automation = self._automation(
            trigger="manual",
            action='create_block "x" on today with priority',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("key=value", result["last_error"])

    def test_create_block_tagged_creates_missing_tag_page(self):
        automation = self._automation(
            trigger="manual",
            action='create_block "x" on today tagged no-such-tag',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        created = Block.objects.get(user=self.user, content__startswith="x")
        self.assertIn("no-such-tag", created.get_tag_names())

    def test_untag_preserves_done_type_and_completed_at(self):
        # Regression: content rewrites go through UpdateBlockCommand, whose
        # prefix auto-detection demotes prefix-less todo-family content to
        # bullet (and clears completed_at). Caught live on staging by the
        # in-app QA agent.
        sticky = PageFactory(user=self.user, title="Sticky", slug="sticky")
        target = self._todo(content="test chore #sticky")
        target.pages.add(sticky)
        target.block_type = "done"
        target.save()
        stamp = timezone.now()
        target.completed_at = stamp
        target.save(update_fields=["completed_at"])

        automation = self._automation(
            trigger="manual",
            query="tag:sticky and completed is not null",
            action="untag sticky",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        target.refresh_from_db()
        self.assertNotIn("#sticky", target.content)
        self.assertEqual(target.block_type, "done")
        self.assertEqual(target.completed_at, stamp)

    def test_set_property_preserves_todo_type(self):
        target = self._todo(content="Buy milk")
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action="set_property priority high",
        )

        self._run(automation)

        target.refresh_from_db()
        self.assertEqual(target.block_type, "todo")
        self.assertEqual(target.properties.get("priority"), "high")


class TestDueRemindClauses(TestCase):
    """`due` / `remind` clauses on create_block and the extended
    `set_due <date> [HH:MM] [remind HH:MM]` grammar — the street-sweeping
    use case: a third-Wednesday cron creates a timed todo with a
    morning reminder."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def _automation(self, **props):
        page = PageFactory(
            user=self.user,
            title="Automations",
            slug=f"automations-{uuid_lib.uuid4().hex[:8]}",
        )
        return BlockFactory(
            user=self.user,
            page=page,
            content="My automation #automation",
            properties=props,
        )

    def _run(self, automation_block, trigger="manual"):
        form = RunAutomationForm(
            {
                "user": self.user,
                "automation_block": automation_block.uuid,
                "trigger": trigger,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        return RunAutomationCommand(form).execute()

    def test_create_block_with_due_time_and_reminder_on_daily(self):
        automation = self._automation(
            trigger="manual",
            action='create_block "move car for street sweeping" on today '
            "as todo due 7:30 remind 7:30",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        created = Block.objects.get(
            user=self.user, content="move car for street sweeping"
        )
        self.assertEqual(created.block_type, "todo")
        self.assertEqual(created.page.page_type, "daily")
        self.assertIsNotNone(created.due_at)
        self.assertTrue(created.due_at_has_time)
        self.assertIsNotNone(created.get_pending_reminder())

    def test_create_block_due_date_only_is_all_day(self):
        PageFactory(user=self.user, title="Inbox", slug="inbox")
        automation = self._automation(
            trigger="manual",
            action='create_block "review" on Inbox due tomorrow',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        created = Block.objects.get(user=self.user, content="review")
        self.assertIsNotNone(created.due_at)
        self.assertFalse(created.due_at_has_time)

    def test_bare_due_time_requires_date_target(self):
        PageFactory(user=self.user, title="Inbox", slug="inbox")
        automation = self._automation(
            trigger="manual",
            action='create_block "x" on Inbox due 7:30',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("needs a date", result["last_error"])

    def test_remind_requires_due_clause(self):
        automation = self._automation(
            trigger="manual",
            action='create_block "x" on today remind 7:30',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("requires a `due` clause", result["last_error"])

    def test_set_due_with_time_and_reminder(self):
        page = PageFactory(user=self.user, slug=f"notes-{uuid_lib.uuid4().hex[:8]}")
        target = BlockFactory(
            user=self.user, page=page, block_type="todo", content="call bank"
        )
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action="set_due tomorrow 14:00 remind 13:30",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        target.refresh_from_db()
        self.assertIsNotNone(target.due_at)
        self.assertTrue(target.due_at_has_time)
        self.assertIsNotNone(target.get_pending_reminder())

    def test_set_due_rejects_garbage_tail(self):
        page = PageFactory(user=self.user, slug=f"notes-{uuid_lib.uuid4().hex[:8]}")
        BlockFactory(user=self.user, page=page, block_type="todo", content="x")
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action="set_due tomorrow banana",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("set_due <date>", result["last_error"])

    def test_set_due_too_many_reminders_fails_loudly(self):
        # Regression: 11 remind clauses passed the bulk form (which only
        # list-checked) and then failed the per-block form inside the
        # loop — every block was classified "missing" and the run
        # recorded SUCCEEDED having scheduled nothing.
        page = PageFactory(user=self.user, slug=f"notes-{uuid_lib.uuid4().hex[:8]}")
        target = BlockFactory(user=self.user, page=page, block_type="todo", content="x")
        reminds = " ".join(f"remind 9:{i:02d}" for i in range(11))
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action=f"set_due tomorrow {reminds}",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("at most 10", result["last_error"])
        target.refresh_from_db()
        self.assertIsNone(target.due_at)

    def test_remind_blank_date_token_fails(self):
        page = PageFactory(user=self.user, slug=f"notes-{uuid_lib.uuid4().hex[:8]}")
        BlockFactory(user=self.user, page=page, block_type="todo", content="x")
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action='set_due tomorrow remind "" 18:00',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("unrecognized date token", result["last_error"])

    def test_create_block_blank_due_token_fails(self):
        automation = self._automation(
            trigger="manual",
            action='create_block "x" on today due "" 14:00',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("unrecognized date token", result["last_error"])
        self.assertFalse(Block.objects.filter(user=self.user, content="x").exists())

    def test_create_block_multiple_reminders(self):
        automation = self._automation(
            trigger="manual",
            action='create_block "move car" on today as todo '
            "due 7:30 remind 7:30 remind 6:45",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        created = Block.objects.get(user=self.user, content="move car")
        pending = Reminder.objects.filter(block=created, sent_at__isnull=True)
        self.assertEqual(pending.count(), 2)

    def test_create_block_dated_reminder_entry(self):
        automation = self._automation(
            trigger="manual",
            action='create_block "prep" on +7d as todo due +7d 14:00 '
            "remind +6d 18:00",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        created = Block.objects.get(user=self.user, content="prep")
        self.assertIsNotNone(created.get_pending_reminder())

    def test_set_due_multiple_reminders(self):
        page = PageFactory(user=self.user, slug=f"notes-{uuid_lib.uuid4().hex[:8]}")
        target = BlockFactory(
            user=self.user, page=page, block_type="todo", content="ship"
        )
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action="set_due tomorrow 14:00 remind 13:30 remind tomorrow 9:00",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        pending = Reminder.objects.filter(block=target, sent_at__isnull=True)
        self.assertEqual(pending.count(), 2)

    def test_bad_remind_spec_fails(self):
        automation = self._automation(
            trigger="manual",
            action='create_block "x" on today due 7:30 remind banana',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("remind", result["last_error"])


class TestParameterizedActions(TestCase):
    """Tokens, grouped map execution, and `for::` iteration (issue #209).
    Asserts external behavior only — end state of blocks/pages and the
    returned run-result dict — never handler internals or grouping order,
    per the issue's testing decisions."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def _automation(self, **props):
        page = PageFactory(
            user=self.user,
            title="Automations",
            slug=f"automations-{uuid_lib.uuid4().hex[:8]}",
        )
        return BlockFactory(
            user=self.user,
            page=page,
            content="My automation #automation",
            properties=props,
        )

    def _run(self, automation_block, trigger="manual"):
        form = RunAutomationForm(
            {
                "user": self.user,
                "automation_block": automation_block.uuid,
                "trigger": trigger,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        return RunAutomationCommand(form).execute()

    def _todo(self, content="TODO ship it", **kwargs):
        page = kwargs.pop(
            "page",
            PageFactory(user=self.user, slug=f"notes-{uuid_lib.uuid4().hex[:8]}"),
        )
        return BlockFactory(
            user=self.user, page=page, block_type="todo", content=content, **kwargs
        )

    # -- grouped map: move_to_page {{block.tag}} -----------------------------

    def test_grouped_move_to_page_by_block_tag_with_mixed_and_ambiguous_tags(self):
        groceries = PageFactory(user=self.user, title="Groceries", slug="groceries")
        urgent = PageFactory(user=self.user, title="Urgent", slug="urgent")
        source = PageFactory(user=self.user, slug=f"notes-{uuid_lib.uuid4().hex[:8]}")

        milk = self._todo(content="TODO milk", page=source)
        milk.pages.add(groceries)
        bread = self._todo(content="TODO bread", page=source)
        bread.pages.add(groceries)
        call_mom = self._todo(content="TODO call mom", page=source)
        call_mom.pages.add(urgent)
        no_tags = self._todo(content="TODO mystery", page=source)
        two_tags = self._todo(content="TODO multi", page=source)
        two_tags.pages.add(groceries)
        two_tags.pages.add(urgent)

        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action="move_to_page {{block.tag}}",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        milk.refresh_from_db()
        bread.refresh_from_db()
        call_mom.refresh_from_db()
        no_tags.refresh_from_db()
        two_tags.refresh_from_db()
        self.assertEqual(milk.page, groceries)
        self.assertEqual(bread.page, groceries)
        self.assertEqual(call_mom.page, urgent)
        # Ambiguous (zero or multiple candidate tags) blocks are skipped,
        # left untouched, while the unambiguous groups still proceed.
        self.assertEqual(no_tags.page, source)
        self.assertEqual(two_tags.page, source)

        skipped_uuids = {s["block_uuid"] for s in result["result"]["skipped"]}
        self.assertEqual(skipped_uuids, {str(no_tags.uuid), str(two_tags.uuid)})
        groups = result["result"]["groups"]
        self.assertEqual(len(groups), 2)
        self.assertEqual(sum(g["count"] for g in groups), 3)
        # No hierarchy in this fixture — every matched block is its own
        # top block, so affected counts all three individually.
        self.assertEqual(result["result"]["affected"], 3)

    def test_except_filter_disambiguates_the_braindumps_sweep(self):
        groceries = PageFactory(user=self.user, title="Groceries", slug="groceries")
        source = PageFactory(user=self.user, slug=f"notes-{uuid_lib.uuid4().hex[:8]}")
        # The canonical braindumps sweep: every braindump block also
        # carries #braindumps and #automation alongside its real
        # destination tag — `except:` strips those before the
        # exactly-one check.
        block = self._todo(content="TODO milk", page=source)
        block.pages.add(groceries)
        braindumps = PageFactory(user=self.user, title="Braindumps", slug="braindumps")
        automation_tag = PageFactory(
            user=self.user, title="Automation", slug="automation"
        )
        block.pages.add(braindumps)
        block.pages.add(automation_tag)

        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action="move_to_page {{block.tag|except:braindumps,automation}}",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        block.refresh_from_db()
        self.assertEqual(block.page, groceries)
        self.assertEqual(result["result"]["skipped"], [])

    def test_grouped_map_keeps_child_riding_with_matched_ancestors_group(self):
        # Hierarchy preservation (story 15): the child's OWN tag differs
        # from its parent's, but it must still ride along with the
        # parent's resolved group, not be independently re-grouped.
        groceries = PageFactory(user=self.user, title="Groceries", slug="groceries")
        urgent = PageFactory(user=self.user, title="Urgent", slug="urgent")
        source = PageFactory(user=self.user, slug=f"notes-{uuid_lib.uuid4().hex[:8]}")
        parent = self._todo(content="TODO parent", page=source)
        parent.pages.add(groceries)
        child = BlockFactory(
            user=self.user,
            page=source,
            parent=parent,
            block_type="todo",
            content="TODO child",
        )
        child.pages.add(urgent)

        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action="move_to_page {{block.tag}}",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        parent.refresh_from_db()
        child.refresh_from_db()
        self.assertEqual(parent.page, groceries)
        self.assertEqual(child.page, groceries)
        self.assertEqual(child.parent, parent)
        self.assertEqual(result["result"]["skipped"], [])

    def test_one_failing_group_is_recorded_while_others_complete(self):
        # Story 14: a group whose resolved target is a template page
        # fails that group only — other groups still complete, and the
        # run itself still succeeds (partial progress, visibly recorded).
        groceries = PageFactory(user=self.user, title="Groceries", slug="groceries")
        pack_template = PageFactory(
            user=self.user, title="Pack", slug="pack", page_type="template"
        )
        source = PageFactory(user=self.user, slug=f"notes-{uuid_lib.uuid4().hex[:8]}")
        good = self._todo(content="TODO milk", page=source)
        good.pages.add(groceries)
        bad = self._todo(content="TODO template thing", page=source)
        bad.pages.add(pack_template)

        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action="move_to_page {{block.tag}}",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        good.refresh_from_db()
        bad.refresh_from_db()
        self.assertEqual(good.page, groceries)
        self.assertEqual(bad.page, source)  # untouched — its group failed

        groups = result["result"]["groups"]
        self.assertEqual(len(groups), 2)
        failed = [g for g in groups if g.get("error")]
        succeeded = [g for g in groups if not g.get("error")]
        self.assertEqual(len(failed), 1)
        self.assertEqual(len(succeeded), 1)
        self.assertIn("template", failed[0]["error"])
        self.assertEqual(result["result"]["affected"], 1)

    def test_grouped_map_respects_cap_with_truncated_flag(self):
        groceries = PageFactory(user=self.user, title="Groceries", slug="groceries")
        urgent = PageFactory(user=self.user, title="Urgent", slug="urgent")
        source = PageFactory(user=self.user, slug=f"notes-{uuid_lib.uuid4().hex[:8]}")
        for i in range(3):
            block = self._todo(content=f"TODO {i}", page=source)
            block.pages.add(groceries if i % 2 == 0 else urgent)
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action="move_to_page {{block.tag}}",
        )

        with patch("knowledge.commands.run_automation_command.MAX_ACTION_BLOCKS", 2):
            result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        self.assertEqual(result["result"]["matched"], 2)
        self.assertTrue(result["result"]["truncated"])

    # -- per-match: create_block {{block.*}} ---------------------------------

    def test_create_block_per_match_one_per_matched_block(self):
        inbox = PageFactory(user=self.user, title="Inbox", slug="inbox")
        source = PageFactory(user=self.user, slug=f"notes-{uuid_lib.uuid4().hex[:8]}")
        self._todo(content="TODO milk", page=source)
        self._todo(content="TODO bread", page=source)

        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action='create_block "Review: {{block.content}}" on Inbox',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        self.assertEqual(result["result"]["affected"], 2)
        contents = set(
            Block.objects.filter(page=inbox).values_list("content", flat=True)
        )
        self.assertEqual(contents, {"Review: milk", "Review: bread"})
        self.assertEqual(len(result["result"]["groups"]), 2)

    def test_create_block_per_match_skips_ambiguous_blocks(self):
        tag_page = PageFactory(user=self.user, title="Groceries", slug="groceries")
        inbox = PageFactory(user=self.user, title="Inbox", slug="inbox")
        source = PageFactory(user=self.user, slug=f"notes-{uuid_lib.uuid4().hex[:8]}")
        tagged = self._todo(content="TODO milk", page=source)
        tagged.pages.add(tag_page)
        untagged = self._todo(content="TODO mystery", page=source)

        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action='create_block "Filed under {{block.tag}}" on Inbox',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        self.assertEqual(result["result"]["affected"], 1)
        self.assertEqual(len(result["result"]["skipped"]), 1)
        self.assertEqual(
            result["result"]["skipped"][0]["block_uuid"], str(untagged.uuid)
        )
        self.assertTrue(
            Block.objects.filter(page=inbox, content="Filed under groceries").exists()
        )

    def test_create_block_per_match_requires_query(self):
        automation = self._automation(
            trigger="manual",
            action='create_block "Review: {{block.content}}" on today',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("query::", result["last_error"])

    # -- for:: fan-out --------------------------------------------------------

    def test_for_fanout_creates_one_block_per_item(self):
        inbox = PageFactory(user=self.user, title="Inbox", slug="inbox")
        automation = self._automation(
            trigger="manual",
            **{"for": "5,10,15"},
            action='create_block "Nudge every {{item}}m" on Inbox',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        contents = set(
            Block.objects.filter(page=inbox).values_list("content", flat=True)
        )
        self.assertEqual(
            contents,
            {"Nudge every 5m", "Nudge every 10m", "Nudge every 15m"},
        )
        self.assertEqual(len(result["result"]["groups"]), 3)
        self.assertEqual(result["result"]["affected"], 3)

    def test_for_fanout_range_form(self):
        inbox = PageFactory(user=self.user, title="Inbox", slug="inbox")
        automation = self._automation(
            trigger="manual",
            **{"for": "5..15 by 5"},
            action='create_block "Nudge every {{item}}m" on Inbox',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        contents = set(
            Block.objects.filter(page=inbox).values_list("content", flat=True)
        )
        self.assertEqual(
            contents,
            {"Nudge every 5m", "Nudge every 10m", "Nudge every 15m"},
        )

    def test_for_fanout_create_block_spawns_automation_family(self):
        # Further Notes: for:: + create_block ... with trigger=... can
        # spawn a family of live automations from one definition.
        inbox = PageFactory(user=self.user, title="Inbox", slug="inbox")
        action = (
            'create_block "Nudge every {{item}}m" on Inbox '
            'with trigger="schedule every {{item}}m" query="type:doing" '
            'action="notify still going"'
        )
        automation = self._automation(
            trigger="manual", **{"for": "5,10"}, action=action
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        created = Block.objects.filter(page=inbox).order_by("content")
        self.assertEqual(created.count(), 2)
        triggers = sorted(b.properties.get("trigger") for b in created)
        self.assertEqual(triggers, ["schedule every 10m", "schedule every 5m"])
        queries = {b.properties.get("query") for b in created}
        self.assertEqual(queries, {"type:doing"})

    # -- {{count}} / {{today}} ambient tokens ---------------------------------

    def test_notify_includes_ambient_match_count(self):
        self.user.discord_webhook_url = "https://discord.example/webhook"
        self.user.save()
        source = PageFactory(user=self.user, slug=f"notes-{uuid_lib.uuid4().hex[:8]}")
        for i in range(3):
            self._todo(content=f"TODO {i}", page=source)
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action='notify "{{count}} items overdue"',
        )

        captured = {}

        def _capture(url, content="", embeds=None, timeout=10.0):
            captured["embeds"] = embeds
            return DiscordDeliveryResult(True, "")

        with patch("knowledge.services.automation_actions.post_webhook", _capture):
            result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        self.assertEqual(captured["embeds"][0]["title"], "3 items overdue")

    def test_set_property_stamps_today_across_a_sweep(self):
        source = PageFactory(user=self.user, slug=f"notes-{uuid_lib.uuid4().hex[:8]}")
        target = self._todo(content="TODO ship it", page=source)
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action="set_property moved_on {{today}}",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        target.refresh_from_db()
        self.assertEqual(
            target.properties.get("moved_on"), self.user.today().isoformat()
        )

    # -- failure modes --------------------------------------------------------

    def test_unknown_token_fails_the_run_and_lists_vocabulary(self):
        self._todo()
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action="tag {{blck.tag}}",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("blck.tag", result["last_error"])
        self.assertIn("block.tag", result["last_error"])

    def test_verb_without_block_token_support_fails_at_run_time(self):
        self.user.discord_webhook_url = "https://discord.example/webhook"
        self.user.save()
        self._todo()
        automation = self._automation(
            trigger="manual",
            query="type:todo",
            action='notify "{{block.tag}}"',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("doesn't support", result["last_error"])

    def test_block_tokens_without_query_fail_at_parse_time(self):
        automation = self._automation(
            trigger="manual",
            action="move_to_page {{block.tag}}",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("query::", result["last_error"])
