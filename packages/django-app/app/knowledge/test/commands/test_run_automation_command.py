from unittest.mock import patch

from django.test import TestCase

from knowledge.commands import RunAutomationCommand
from knowledge.forms.run_automation_form import RunAutomationForm
from knowledge.models import AutomationRun
from knowledge.repositories import SavedViewRepository

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
        page = PageFactory(user=self.user, title="Automations", slug="automations-pg")
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

    def test_disabled_automation_is_skipped(self):
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
            enabled="false",
        )

        result = self._run(automation)

        self.assertEqual(result["status"], AutomationRun.STATUS_SKIPPED)
        target.refresh_from_db()
        self.assertEqual(target.page, source)

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
