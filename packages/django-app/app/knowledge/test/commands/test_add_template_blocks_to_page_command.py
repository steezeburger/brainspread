from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase

from knowledge.commands import AddTemplateBlocksToPageCommand
from knowledge.forms import AddTemplateBlocksToPageForm
from knowledge.models import Block

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestAddTemplateBlocksToPageCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def test_should_append_template_blocks_to_target(self):
        template = PageFactory(
            user=self.user,
            title="Morning Routine",
            slug="morning-routine",
            page_type="template",
        )
        BlockFactory(user=self.user, page=template, content="make coffee", order=1)
        BlockFactory(user=self.user, page=template, content="review calendar", order=2)

        target = PageFactory(
            user=self.user, title="Today", slug="today", page_type="daily"
        )
        BlockFactory(user=self.user, page=target, content="existing", order=1)

        form = AddTemplateBlocksToPageForm(
            {
                "user": self.user,
                "template": template.uuid,
                "target_page": target.uuid,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        result = AddTemplateBlocksToPageCommand(form).execute()

        self.assertEqual(result["added"], 2)
        # Target now has the original block plus the two cloned ones,
        # ordered after the existing block.
        target_blocks = list(Block.objects.filter(page=target).order_by("order"))
        self.assertEqual(len(target_blocks), 3)
        self.assertEqual(target_blocks[0].content, "existing")
        self.assertEqual(target_blocks[1].content, "make coffee")
        self.assertEqual(target_blocks[2].content, "review calendar")

    def test_should_preserve_template_block_hierarchy(self):
        template = PageFactory(
            user=self.user,
            title="Project Kickoff",
            slug="project-kickoff",
            page_type="template",
        )
        parent = BlockFactory(user=self.user, page=template, content="parent", order=1)
        BlockFactory(
            user=self.user,
            page=template,
            parent=parent,
            content="child",
            order=2,
        )

        target = PageFactory(user=self.user, title="New Project", slug="new-project")

        form = AddTemplateBlocksToPageForm(
            {
                "user": self.user,
                "template": template.uuid,
                "target_page": target.uuid,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        AddTemplateBlocksToPageCommand(form).execute()

        target_blocks = list(Block.objects.filter(page=target).order_by("order"))
        self.assertEqual(len(target_blocks), 2)
        parent_clone, child_clone = target_blocks
        self.assertIsNone(parent_clone.parent_id)
        self.assertEqual(child_clone.parent_id, parent_clone.id)

    def test_should_leave_template_blocks_alone(self):
        # The cloned blocks must be new rows — modifying them in the
        # target should not touch the template.
        template = PageFactory(
            user=self.user, title="Tpl", slug="tpl", page_type="template"
        )
        src = BlockFactory(user=self.user, page=template, content="todo", order=1)
        target = PageFactory(user=self.user, title="Mine", slug="mine")

        form = AddTemplateBlocksToPageForm(
            {
                "user": self.user,
                "template": template.uuid,
                "target_page": target.uuid,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        AddTemplateBlocksToPageCommand(form).execute()

        cloned = Block.objects.get(page=target)
        cloned.content = "todo — done"
        cloned.save()

        src.refresh_from_db()
        self.assertEqual(src.content, "todo")

    def test_should_reject_non_template_source(self):
        # A non-template page can't be used as the source; the user
        # should pick a template-typed page or fall back to the
        # duplicate-page flow.
        regular_source = PageFactory(
            user=self.user, title="Notes", slug="notes", page_type="page"
        )
        target = PageFactory(user=self.user, title="T", slug="t")

        form = AddTemplateBlocksToPageForm(
            {
                "user": self.user,
                "template": regular_source.uuid,
                "target_page": target.uuid,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("template", form.errors)

    def test_should_reject_template_as_target(self):
        # Don't let users accidentally bloat a template with another's
        # contents by misusing this flow.
        template = PageFactory(
            user=self.user, title="A", slug="a", page_type="template"
        )
        other_template = PageFactory(
            user=self.user, title="B", slug="b", page_type="template"
        )

        form = AddTemplateBlocksToPageForm(
            {
                "user": self.user,
                "template": template.uuid,
                "target_page": other_template.uuid,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("target_page", form.errors)

    def test_should_reject_template_from_other_user(self):
        other_user = UserFactory()
        their_template = PageFactory(
            user=other_user, title="theirs", slug="theirs", page_type="template"
        )
        target = PageFactory(user=self.user, title="Mine", slug="mine")

        form = AddTemplateBlocksToPageForm(
            {
                "user": self.user,
                "template": their_template.uuid,
                "target_page": target.uuid,
            }
        )
        self.assertFalse(form.is_valid())

    def test_should_reject_target_from_other_user(self):
        template = PageFactory(
            user=self.user, title="T", slug="t", page_type="template"
        )
        other_user = UserFactory()
        their_page = PageFactory(
            user=other_user, title="theirs", slug="theirs", page_type="page"
        )

        form = AddTemplateBlocksToPageForm(
            {
                "user": self.user,
                "template": template.uuid,
                "target_page": their_page.uuid,
            }
        )
        self.assertFalse(form.is_valid())


class TestTemplateApplyTokens(TestCase):
    """Apply is the resolve boundary for {{tokens}} (issue #140):
    dormant in the template, frozen into the cloned copies."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def _apply(self, template, target, inputs=None):
        data = {
            "user": self.user,
            "template": template.uuid,
            "target_page": target.uuid,
        }
        if inputs is not None:
            data["inputs"] = inputs
        form = AddTemplateBlocksToPageForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        return AddTemplateBlocksToPageCommand(form).execute()

    def _template(self, *contents):
        template = PageFactory(user=self.user, page_type="template")
        for order, content in enumerate(contents, start=1):
            BlockFactory(user=self.user, page=template, content=content, order=order)
        return template

    def _target_contents(self, target):
        return [b.content for b in Block.objects.filter(page=target).order_by("order")]

    def test_tokens_stay_dormant_in_template_and_resolve_on_apply(self):
        template = self._template("standup {{today}}", "on {{page.title}}")
        target = PageFactory(user=self.user, title="Sprint Board", page_type="page")

        result = self._apply(template, target)

        self.assertEqual(result["added"], 2)
        self.assertEqual(result["needs_input"], [])
        self.assertEqual(
            self._target_contents(target),
            [
                f"standup {self.user.today().isoformat()}",
                "on Sprint Board",
            ],
        )
        # The template's own blocks still carry the raw tokens.
        template_contents = [b.content for b in Block.objects.filter(page=template)]
        self.assertIn("standup {{today}}", template_contents)

    def test_apply_reports_needed_inputs_and_clones_nothing(self):
        template = self._template(
            "Project {{input:name}}", "Goal: {{input:goal}} for {{input:name}}"
        )
        target = PageFactory(user=self.user, page_type="page")

        result = self._apply(template, target)

        self.assertEqual(result["added"], 0)
        self.assertEqual(result["needs_input"], ["name", "goal"])
        self.assertEqual(Block.objects.filter(page=target).count(), 0)

    def test_apply_substitutes_provided_inputs(self):
        template = self._template("Project {{input:name}}")
        target = PageFactory(user=self.user, page_type="page")

        result = self._apply(template, target, inputs={"name": "Q3 launch"})

        self.assertEqual(result["added"], 1)
        self.assertEqual(result["needs_input"], [])
        self.assertEqual(self._target_contents(target), ["Project Q3 launch"])

    def test_named_uuid_is_shared_across_the_apply(self):
        template = self._template("root {{uuid|name:proj}}", "{{uuid|name:proj}}")
        target = PageFactory(user=self.user, page_type="page")

        self._apply(template, target)

        first, second = self._target_contents(target)
        shared_id = first.removeprefix("root ")
        self.assertEqual(second, shared_id)
        self.assertEqual(len(shared_id), 36)

    def test_count_token_freezes_at_apply(self):
        target = PageFactory(user=self.user, page_type="daily")
        BlockFactory(user=self.user, page=target, block_type="todo", order=1)
        BlockFactory(user=self.user, page=target, block_type="todo", order=2)
        template = self._template(
            "Open going into the week: " "{{count:type:todo and completed is null}}"
        )

        self._apply(template, target)

        contents = self._target_contents(target)
        self.assertIn("Open going into the week: 2", contents)

    def test_resolved_properties_are_extracted(self):
        template = self._template("carried:: {{today}}")
        target = PageFactory(user=self.user, page_type="page")

        self._apply(template, target)

        block = Block.objects.filter(page=target).first()
        self.assertEqual(block.properties.get("carried"), self.user.today().isoformat())

    def test_resolved_input_hashtag_is_tag_synced(self):
        template = self._template("task {{input:tag}}")
        target = PageFactory(user=self.user, page_type="page")

        self._apply(template, target, inputs={"tag": "#urgent"})

        block = Block.objects.filter(page=target).first()
        self.assertEqual(block.content, "task #urgent")
        self.assertIn("urgent", [p.slug for p in block.pages.all()])

    def test_unknown_token_in_template_fails_the_apply(self):
        template = self._template("hello {{blorp}}")
        target = PageFactory(user=self.user, page_type="page")

        with self.assertRaises(DjangoValidationError):
            self._apply(template, target)
        # The transaction rolled back — nothing landed on the target.
        self.assertEqual(Block.objects.filter(page=target).count(), 0)
