from django.test import SimpleTestCase

from knowledge.services.query_dsl import QueryDSLError, compile_inline_query


class TestCompileInlineQuery(SimpleTestCase):
    def test_single_predicates_map_one_to_one(self):
        self.assertEqual(compile_inline_query("tag:sticky"), {"has_tag": "sticky"})
        self.assertEqual(compile_inline_query("type:doing"), {"block_type": "doing"})
        self.assertEqual(
            compile_inline_query("type:todo,doing"),
            {"block_type": {"in": ["todo", "doing"]}},
        )
        self.assertEqual(
            compile_inline_query("has:project"), {"has_property": "project"}
        )
        self.assertEqual(
            compile_inline_query('content:"foo bar"'),
            {"content_contains": "foo bar"},
        )
        self.assertEqual(
            compile_inline_query("prop:priority=high"),
            {"property_eq": {"key": "priority", "eq": "high"}},
        )
        self.assertEqual(
            compile_inline_query("page_type:template"), {"page_type": "template"}
        )

    def test_date_comparisons_and_aliases(self):
        self.assertEqual(
            compile_inline_query("due < today"), {"due_at": {"lt": "today"}}
        )
        self.assertEqual(
            compile_inline_query("scheduled < today"), {"due_at": {"lt": "today"}}
        )
        self.assertEqual(
            compile_inline_query('completed >= "7 days ago"'),
            {"completed_at": {"gte": "7 days ago"}},
        )
        self.assertEqual(compile_inline_query("due:today"), {"due_at": "today"})
        self.assertEqual(
            compile_inline_query("due is null"), {"due_at": {"is_null": True}}
        )
        self.assertEqual(
            compile_inline_query("completed is not null"),
            {"completed_at": {"is_null": False}},
        )

    def test_boolean_combinators_and_precedence(self):
        # not > and > or
        self.assertEqual(
            compile_inline_query("tag:a and type:todo"),
            {"all": [{"has_tag": "a"}, {"block_type": "todo"}]},
        )
        self.assertEqual(
            compile_inline_query("tag:a or tag:b"),
            {"any": [{"has_tag": "a"}, {"has_tag": "b"}]},
        )
        self.assertEqual(
            compile_inline_query("not tag:archived"),
            {"not": {"has_tag": "archived"}},
        )
        self.assertEqual(
            compile_inline_query("tag:a and tag:b or tag:c"),
            {
                "any": [
                    {"all": [{"has_tag": "a"}, {"has_tag": "b"}]},
                    {"has_tag": "c"},
                ]
            },
        )
        self.assertEqual(
            compile_inline_query("tag:a and (tag:b or tag:c)"),
            {
                "all": [
                    {"has_tag": "a"},
                    {"any": [{"has_tag": "b"}, {"has_tag": "c"}]},
                ]
            },
        )
        self.assertEqual(
            compile_inline_query("tag:a and not tag:b"),
            {"all": [{"has_tag": "a"}, {"not": {"has_tag": "b"}}]},
        )

    def test_ping_me_15_expression(self):
        self.assertEqual(
            compile_inline_query("tag:ping-me-15 and type:doing"),
            {"all": [{"has_tag": "ping-me-15"}, {"block_type": "doing"}]},
        )

    def test_errors_are_specific(self):
        with self.assertRaises(QueryDSLError):
            compile_inline_query("")
        with self.assertRaises(QueryDSLError):
            compile_inline_query("tag:")
        with self.assertRaises(QueryDSLError):
            compile_inline_query("bogus~~query")
        with self.assertRaises(QueryDSLError):
            compile_inline_query("tag:a and")
        with self.assertRaises(QueryDSLError):
            compile_inline_query("(tag:a or tag:b")
        with self.assertRaises(QueryDSLError):
            compile_inline_query("unknownfield < today")
        with self.assertRaises(QueryDSLError):
            compile_inline_query("prop:missing-eq")
        with self.assertRaises(QueryDSLError) as ctx:
            compile_inline_query("#sticky")
        self.assertIn("tag:", str(ctx.exception))
