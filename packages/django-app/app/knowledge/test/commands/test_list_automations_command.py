from django.test import TestCase

from knowledge.commands import ListAutomationsCommand, RunAutomationCommand
from knowledge.forms.list_automations_form import ListAutomationsForm
from knowledge.forms.run_automation_form import RunAutomationForm
from knowledge.models import AutomationRun

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestListAutomationsCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.tag_page = PageFactory(user=cls.user, title="automation", slug="automation")

    def _automation(self, content: str, props: dict):
        page = PageFactory(user=self.user, title="Autos", slug=f"autos-{len(content)}")
        block = BlockFactory(
            user=self.user, page=page, content=content, properties=props
        )
        block.pages.add(self.tag_page)
        return block

    def test_lists_valid_and_malformed_definitions(self):
        good = self._automation(
            "Sweep stickies #automation",
            {
                "trigger": "schedule daily 6:00",
                "query": "tag:sticky and type:todo",
                "action": "move_to_daily today",
                "allow": "move_to_daily",
            },
        )
        broken = self._automation("Broken one #automation", {"trigger": "telepathy"})

        form = ListAutomationsForm({"user": self.user.id})
        self.assertTrue(form.is_valid(), form.errors)
        rows = ListAutomationsCommand(form).execute()

        by_uuid = {row["block_uuid"]: row for row in rows}
        self.assertEqual(len(rows), 2)

        good_row = by_uuid[str(good.uuid)]
        self.assertEqual(good_row["name"], "Sweep stickies")
        self.assertEqual(good_row["slug"], "sweep-stickies")
        self.assertEqual(good_row["trigger"], "schedule")
        self.assertTrue(good_row["enabled"])
        self.assertIsNone(good_row["parse_error"])
        self.assertIsNone(good_row["last_run"])

        broken_row = by_uuid[str(broken.uuid)]
        self.assertIsNotNone(broken_row["parse_error"])
        self.assertIn("telepathy", broken_row["parse_error"])

    def test_includes_last_run_summary(self):
        automation = self._automation(
            "Runs sometimes #automation",
            {"trigger": "manual", "action": 'notify "hi"', "allow": "notify"},
        )
        run_form = RunAutomationForm(
            {"user": self.user, "automation_block": automation.uuid}
        )
        self.assertTrue(run_form.is_valid(), run_form.errors)
        RunAutomationCommand(run_form).execute()

        form = ListAutomationsForm({"user": self.user.id})
        self.assertTrue(form.is_valid(), form.errors)
        rows = ListAutomationsCommand(form).execute()

        self.assertEqual(len(rows), 1)
        last_run = rows[0]["last_run"]
        self.assertIsNotNone(last_run)
        # No webhook configured — the run failed, and the listing says so.
        self.assertEqual(last_run["status"], AutomationRun.STATUS_FAILED)


class TestRunAutomationBySlug(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.tag_page = PageFactory(user=cls.user, title="automation", slug="automation")
        page = PageFactory(user=cls.user, title="Autos", slug="autos-slug")
        cls.automation = BlockFactory(
            user=cls.user,
            page=page,
            content="Morning sweep #automation",
            properties={
                "trigger": "manual",
                "query": "type:todo",
                "action": "set_type done",
                "allow": "set_type",
            },
        )
        cls.automation.pages.add(cls.tag_page)

    def test_runs_by_derived_slug(self):
        notes = PageFactory(user=self.user, title="Notes", slug="notes-slug")
        todo = BlockFactory(
            user=self.user, page=notes, block_type="todo", content="TODO x"
        )

        form = RunAutomationForm(
            {"user": self.user, "automation_slug": "morning-sweep"}
        )
        self.assertTrue(form.is_valid(), form.errors)
        result = RunAutomationCommand(form).execute()

        self.assertEqual(result["status"], AutomationRun.STATUS_SUCCEEDED)
        todo.refresh_from_db()
        self.assertEqual(todo.block_type, "done")

    def test_unknown_slug_is_a_form_error(self):
        form = RunAutomationForm(
            {"user": self.user, "automation_slug": "no-such-automation"}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("no-such-automation", str(form.errors))

    def test_missing_both_references_is_a_form_error(self):
        form = RunAutomationForm({"user": self.user})
        self.assertFalse(form.is_valid())


class TestToolRegistration(TestCase):
    def test_automation_tools_registered_on_both_surfaces(self):
        from ai_chat.tools.notes_tools import NOTES_READ_TOOLS, NOTES_WRITE_TOOLS
        from mcp_server.tools import REGISTRY

        read_names = {tool.name for tool in NOTES_READ_TOOLS}
        write_names = {tool.name for tool in NOTES_WRITE_TOOLS}
        self.assertIn("list_automations", read_names)
        self.assertIn("run_automation", write_names)

        self.assertIn("list_automations", REGISTRY)
        self.assertIn("run_automation", REGISTRY)
        self.assertTrue(REGISTRY.get("run_automation").is_write)
        self.assertFalse(REGISTRY.get("list_automations").is_write)
