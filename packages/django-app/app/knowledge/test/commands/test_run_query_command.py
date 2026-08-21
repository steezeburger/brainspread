from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from knowledge.commands import RunQueryCommand
from knowledge.forms import RunQueryForm
from knowledge.test.helpers import BlockFactory, PageFactory, UserFactory


class TestRunQueryCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(timezone="UTC")
        cls.page = PageFactory(user=cls.user, title="Project Alpha", slug="alpha")

    def _run(self, **data):
        form = RunQueryForm({"user": self.user, **data})
        self.assertTrue(form.is_valid(), form.errors)
        return RunQueryCommand(form).execute()

    def test_dsl_expression_filters_and_shapes_rows(self):
        todo = BlockFactory(
            user=self.user, page=self.page, block_type="todo", content="TODO ship"
        )
        BlockFactory(
            user=self.user, page=self.page, block_type="bullet", content="note"
        )

        result = self._run(query="type:todo")

        self.assertEqual(result["count"], 1)
        self.assertFalse(result["truncated"])
        row = result["results"][0]
        self.assertEqual(row["block_uuid"], str(todo.uuid))
        self.assertEqual(row["page_title"], "Project Alpha")
        self.assertEqual(row["page_slug"], "alpha")
        self.assertEqual(row["block_type"], "todo")
        self.assertEqual(row["content"], "TODO ship")
        self.assertIsNone(row["due_at"])

    def test_bare_text_query_is_content_search(self):
        BlockFactory(
            user=self.user, page=self.page, content="meeting with bob tomorrow"
        )
        BlockFactory(user=self.user, page=self.page, content="grocery list")

        result = self._run(query="meeting with bob")

        self.assertEqual(result["count"], 1)
        self.assertIn("meeting with bob", result["results"][0]["content"])

    def test_raw_filter_escape_hatch(self):
        BlockFactory(
            user=self.user, page=self.page, block_type="todo", content="TODO x"
        )

        result = self._run(filter={"block_type": "todo"})

        self.assertEqual(result["count"], 1)

    def test_scopes_to_user(self):
        other = UserFactory()
        other_page = PageFactory(user=other, title="Theirs", slug="theirs")
        BlockFactory(user=other, page=other_page, content="secret meeting")

        result = self._run(query="meeting")

        self.assertEqual(result["count"], 0)

    def test_sort_and_limit_with_truncation(self):
        now = timezone.now()
        for i in range(3):
            BlockFactory(
                user=self.user,
                page=self.page,
                block_type="todo",
                content=f"TODO {i}",
                due_at=now + timedelta(days=i),
                due_at_has_time=True,
            )

        result = self._run(
            query="type:todo",
            sort=[{"field": "due_at", "dir": "desc"}],
            limit=2,
        )

        self.assertEqual(result["count"], 2)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["results"][0]["content"], "TODO 2")

    def test_requires_exactly_one_of_query_or_filter(self):
        neither = RunQueryForm({"user": self.user})
        self.assertFalse(neither.is_valid())

        both = RunQueryForm(
            {"user": self.user, "query": "type:todo", "filter": {"block_type": "todo"}}
        )
        self.assertFalse(both.is_valid())

    def test_bad_dsl_is_a_form_error_with_parser_message(self):
        form = RunQueryForm({"user": self.user, "query": "due <"})
        self.assertFalse(form.is_valid())
        self.assertIn("bad query", str(form.errors))

    def test_bad_raw_filter_raises_validation_error(self):
        from django.core.exceptions import ValidationError

        form = RunQueryForm({"user": self.user, "filter": {"bogus_field": "x"}})
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(ValidationError):
            RunQueryCommand(form).execute()
