import uuid as uuid_lib
from unittest.mock import patch

from django.test import TestCase

from knowledge.commands import RunAutomationCommand
from knowledge.forms.run_automation_form import RunAutomationForm
from knowledge.models import AutomationRun, Block
from knowledge.repositories import AutomationRunRepository, SavedViewRepository

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

    def test_move_to_page_rejects_missing_and_template_targets(self):
        PageFactory(user=self.user, title="Pack", slug="pack-tpl", page_type="template")
        source = PageFactory(user=self.user, title="Notes", slug="notes-mtp3")
        BlockFactory(user=self.user, page=source, block_type="todo", content="TODO x")

        missing = self._automation(
            trigger="manual", query="type:todo", action='move_to_page "nope"'
        )
        result = self._run(missing)
        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("not found", result["last_error"])

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

    def test_tag_missing_page_fails_instead_of_creating(self):
        self._todo()
        automation = self._automation(
            trigger="manual", query="type:todo", action="tag no-such-tag"
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("no-such-tag", result["last_error"])

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

    def test_create_block_tagged_missing_page_fails(self):
        automation = self._automation(
            trigger="manual",
            action='create_block "x" on today tagged no-such-tag',
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("no-such-tag", result["last_error"])

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
        from django.utils import timezone as dj_tz

        stamp = dj_tz.now()
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
