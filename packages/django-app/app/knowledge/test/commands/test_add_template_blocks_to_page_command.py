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
