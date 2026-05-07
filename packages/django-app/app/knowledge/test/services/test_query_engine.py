"""Query engine tests (issue #60).

Each predicate has a happy path + at least one rejection / boundary
case. Combinator coverage focuses on the multi-``has_tag`` AND case
that would silently break under a naive single-join translator (the
"Glitch's favorite things" example from #60), plus OR-of-tags and
nested combinations.
"""

from datetime import date, datetime
from unittest.mock import patch

import pytz
from django.test import TestCase

from knowledge.repositories import BlockRepository
from knowledge.services import query_engine

from ..helpers import BlockFactory, PageFactory, UserFactory


def _utc_noon(d: date) -> datetime:
    """Aware UTC datetime at noon, used to drive User.today() so relative
    date tokens (``today``, ``N days ago``) resolve to a known target."""
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=pytz.UTC)


class _EngineTestBase(TestCase):
    """Base TestCase that pins ``today()`` to 2026-04-24 in UTC and
    exposes a ``run(spec, sort=None, limit=None)`` helper that compiles
    + executes against ``self.user``."""

    today = date(2026, 4, 24)

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(timezone="UTC")
        cls.other_user = UserFactory(timezone="UTC")
        cls.page = PageFactory(user=cls.user, page_type="page", title="Notes")

    def setUp(self):
        super().setUp()
        patcher = patch("core.models.user.timezone")
        self.mock_tz = patcher.start()
        self.mock_tz.now.return_value = _utc_noon(self.today)
        self.addCleanup(patcher.stop)

    def run_query(self, spec, sort=None, limit=None):
        compiled = query_engine.compile(spec, user=self.user, sort=sort)
        return list(
            BlockRepository.run_compiled_query(self.user, compiled, limit=limit)
        )


class BlockTypeTests(_EngineTestBase):
    def test_eq_shorthand_string(self):
        match = BlockFactory(user=self.user, page=self.page, block_type="todo")
        BlockFactory(user=self.user, page=self.page, block_type="bullet")
        out = self.run_query({"block_type": "todo"})
        self.assertEqual([b.id for b in out], [match.id])

    def test_in_op(self):
        a = BlockFactory(user=self.user, page=self.page, block_type="todo")
        b = BlockFactory(user=self.user, page=self.page, block_type="doing")
        BlockFactory(user=self.user, page=self.page, block_type="bullet")
        out = self.run_query({"block_type": {"in": ["todo", "doing"]}})
        self.assertEqual({b.id for b in out}, {a.id, b.id})

    def test_unknown_value_rejected(self):
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile({"block_type": "tdo"}, user=self.user)

    def test_unsupported_op_rejected(self):
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile({"block_type": {"like": "todo"}}, user=self.user)


class ScheduledForTests(_EngineTestBase):
    def test_lt_today_token(self):
        yesterday = BlockFactory(
            user=self.user,
            page=self.page,
            scheduled_for=date(2026, 4, 23),
            block_type="todo",
        )
        BlockFactory(
            user=self.user,
            page=self.page,
            scheduled_for=date(2026, 4, 25),
            block_type="todo",
        )
        out = self.run_query({"scheduled_for": {"lt": "today"}})
        self.assertEqual([b.id for b in out], [yesterday.id])

    def test_between_inclusive(self):
        a = BlockFactory(
            user=self.user, page=self.page, scheduled_for=date(2026, 4, 23)
        )
        b = BlockFactory(
            user=self.user, page=self.page, scheduled_for=date(2026, 4, 25)
        )
        BlockFactory(user=self.user, page=self.page, scheduled_for=date(2026, 5, 1))
        out = self.run_query(
            {"scheduled_for": {"between": ["2026-04-23", "2026-04-25"]}}
        )
        self.assertEqual({b.id for b in out}, {a.id, b.id})

    def test_iso_eq(self):
        match = BlockFactory(
            user=self.user, page=self.page, scheduled_for=date(2026, 5, 1)
        )
        BlockFactory(user=self.user, page=self.page, scheduled_for=date(2026, 5, 2))
        out = self.run_query({"scheduled_for": "2026-05-01"})
        self.assertEqual([b.id for b in out], [match.id])

    def test_n_days_ago_token(self):
        # 7 days ago = 2026-04-17
        match = BlockFactory(
            user=self.user, page=self.page, scheduled_for=date(2026, 4, 17)
        )
        BlockFactory(user=self.user, page=self.page, scheduled_for=date(2026, 4, 18))
        out = self.run_query({"scheduled_for": {"eq": "7 days ago"}})
        self.assertEqual([b.id for b in out], [match.id])

    def test_unrecognized_token_rejected(self):
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile({"scheduled_for": {"lt": "soon-ish"}}, user=self.user)


class CompletedAtTests(_EngineTestBase):
    def test_is_null_true_excludes_completed(self):
        open_block = BlockFactory(
            user=self.user, page=self.page, completed_at=None, block_type="todo"
        )
        BlockFactory(
            user=self.user,
            page=self.page,
            completed_at=_utc_noon(date(2026, 4, 24)),
            block_type="done",
        )
        out = self.run_query({"completed_at": {"is_null": True}})
        self.assertEqual([b.id for b in out], [open_block.id])

    def test_gte_n_days_ago_uses_local_day_boundary(self):
        # 7 days ago = 2026-04-17. completed at 23:59 on 2026-04-16 UTC
        # is BEFORE that boundary; completed at 00:01 on 2026-04-17 UTC
        # is AFTER (user.timezone='UTC').
        before = BlockFactory(
            user=self.user,
            page=self.page,
            completed_at=datetime(2026, 4, 16, 23, 59, tzinfo=pytz.UTC),
        )
        after = BlockFactory(
            user=self.user,
            page=self.page,
            completed_at=datetime(2026, 4, 17, 0, 1, tzinfo=pytz.UTC),
        )
        out = self.run_query({"completed_at": {"gte": "7 days ago"}})
        out_ids = {b.id for b in out}
        self.assertIn(after.id, out_ids)
        self.assertNotIn(before.id, out_ids)


class HasTagTests(_EngineTestBase):
    def _tag(self, block, page):
        block.pages.add(page)
        return block

    def test_single_tag(self):
        glitch = PageFactory(user=self.user, slug="glitch", title="Glitch")
        match = self._tag(BlockFactory(user=self.user, page=self.page), glitch)
        BlockFactory(user=self.user, page=self.page)
        out = self.run_query({"has_tag": "glitch"})
        self.assertEqual([b.id for b in out], [match.id])

    def test_multi_tag_under_all_requires_both_tags(self):
        """The 'Glitch's favorite things' case from issue #60 — a single
        ``pages__slug__in=[...]`` would match blocks tagged with EITHER
        slug; we need an Exists per tag to require BOTH."""
        glitch = PageFactory(user=self.user, slug="glitch", title="Glitch")
        favs = PageFactory(user=self.user, slug="favorite-things", title="Favs")

        only_glitch = BlockFactory(user=self.user, page=self.page)
        only_glitch.pages.add(glitch)

        only_favs = BlockFactory(user=self.user, page=self.page)
        only_favs.pages.add(favs)

        both = BlockFactory(user=self.user, page=self.page)
        both.pages.add(glitch)
        both.pages.add(favs)

        out = self.run_query(
            {
                "all": [
                    {"has_tag": "glitch"},
                    {"has_tag": "favorite-things"},
                ]
            }
        )
        self.assertEqual([b.id for b in out], [both.id])
        self.assertNotIn(only_glitch.id, {b.id for b in out})
        self.assertNotIn(only_favs.id, {b.id for b in out})

    def test_any_tag_OR(self):
        a_page = PageFactory(user=self.user, slug="alpha", title="Alpha")
        b_page = PageFactory(user=self.user, slug="beta", title="Beta")
        a = BlockFactory(user=self.user, page=self.page)
        a.pages.add(a_page)
        b = BlockFactory(user=self.user, page=self.page)
        b.pages.add(b_page)
        BlockFactory(user=self.user, page=self.page)  # untagged

        out = self.run_query({"any": [{"has_tag": "alpha"}, {"has_tag": "beta"}]})
        self.assertEqual({b.id for b in out}, {a.id, b.id})

    def test_cross_user_tag_isolation(self):
        """A page slug match must not leak across users — slugs are
        unique per user, so two users can each have a `#glitch` page."""
        my_glitch = PageFactory(user=self.user, slug="glitch", title="Mine")
        other_glitch = PageFactory(user=self.other_user, slug="glitch", title="Other")

        my_block = BlockFactory(user=self.user, page=self.page)
        my_block.pages.add(my_glitch)

        their_page = PageFactory(user=self.other_user, page_type="page", title="Theirs")
        their_block = BlockFactory(user=self.other_user, page=their_page)
        their_block.pages.add(other_glitch)

        out = self.run_query({"has_tag": "glitch"})
        self.assertEqual([b.id for b in out], [my_block.id])

    def test_empty_slug_rejected(self):
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile({"has_tag": ""}, user=self.user)


class HasPropertyTests(_EngineTestBase):
    def test_key_present(self):
        match = BlockFactory(
            user=self.user, page=self.page, properties={"priority": "high"}
        )
        BlockFactory(user=self.user, page=self.page, properties={})
        out = self.run_query({"has_property": "priority"})
        self.assertEqual([b.id for b in out], [match.id])

    def test_empty_key_rejected(self):
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile({"has_property": ""}, user=self.user)


class PropertyEqTests(_EngineTestBase):
    def test_match(self):
        a = BlockFactory(
            user=self.user, page=self.page, properties={"priority": "high"}
        )
        BlockFactory(user=self.user, page=self.page, properties={"priority": "low"})
        out = self.run_query({"property_eq": {"key": "priority", "value": "high"}})
        self.assertEqual([b.id for b in out], [a.id])

    def test_missing_value_rejected(self):
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile({"property_eq": {"key": "priority"}}, user=self.user)


class ContentContainsTests(_EngineTestBase):
    def test_icontains_match(self):
        a = BlockFactory(user=self.user, page=self.page, content="Buy MILK")
        BlockFactory(user=self.user, page=self.page, content="Buy bread")
        out = self.run_query({"content_contains": "milk"})
        self.assertEqual([b.id for b in out], [a.id])


class CombinatorTests(_EngineTestBase):
    def test_overdue_predicate_via_all(self):
        """Issue #60's headline filter — same predicate as the migrated
        Overdue section, expressed declaratively."""
        yesterday = date(2026, 4, 23)
        match = BlockFactory(
            user=self.user,
            page=self.page,
            block_type="todo",
            scheduled_for=yesterday,
            completed_at=None,
        )
        # done — excluded
        BlockFactory(
            user=self.user,
            page=self.page,
            block_type="done",
            scheduled_for=yesterday,
            completed_at=_utc_noon(self.today),
        )
        # todo but completed — excluded
        BlockFactory(
            user=self.user,
            page=self.page,
            block_type="todo",
            scheduled_for=yesterday,
            completed_at=_utc_noon(self.today),
        )
        # not yet due — excluded
        BlockFactory(
            user=self.user,
            page=self.page,
            block_type="todo",
            scheduled_for=date(2026, 4, 25),
            completed_at=None,
        )
        out = self.run_query(
            {
                "all": [
                    {"block_type": {"in": ["todo", "doing", "later"]}},
                    {"scheduled_for": {"lt": "today"}},
                    {"completed_at": {"is_null": True}},
                ]
            }
        )
        self.assertEqual([b.id for b in out], [match.id])

    def test_nested_any_inside_all(self):
        """``project-x AND (todo OR doing) AND not completed``."""
        proj = PageFactory(user=self.user, slug="project-x", title="Project X")

        match = BlockFactory(
            user=self.user, page=self.page, block_type="todo", completed_at=None
        )
        match.pages.add(proj)

        # has tag, but block_type=bullet — excluded
        excluded_bullet = BlockFactory(
            user=self.user, page=self.page, block_type="bullet", completed_at=None
        )
        excluded_bullet.pages.add(proj)

        # has tag, todo, but completed — excluded
        excluded_done = BlockFactory(
            user=self.user,
            page=self.page,
            block_type="todo",
            completed_at=_utc_noon(self.today),
        )
        excluded_done.pages.add(proj)

        out = self.run_query(
            {
                "all": [
                    {"has_tag": "project-x"},
                    {"any": [{"block_type": "todo"}, {"block_type": "doing"}]},
                    {"completed_at": {"is_null": True}},
                ]
            }
        )
        self.assertEqual([b.id for b in out], [match.id])


class SortTests(_EngineTestBase):
    def test_sort_asc_by_scheduled_for(self):
        a = BlockFactory(
            user=self.user, page=self.page, scheduled_for=date(2026, 4, 23)
        )
        b = BlockFactory(
            user=self.user, page=self.page, scheduled_for=date(2026, 4, 21)
        )
        c = BlockFactory(
            user=self.user, page=self.page, scheduled_for=date(2026, 4, 22)
        )
        out = self.run_query(
            {"scheduled_for": {"lt": "today"}},
            sort=[{"field": "scheduled_for", "dir": "asc"}],
        )
        self.assertEqual([blk.id for blk in out], [b.id, c.id, a.id])

    def test_sort_desc_by_completed_at(self):
        a = BlockFactory(
            user=self.user,
            page=self.page,
            completed_at=datetime(2026, 4, 24, 9, 0, tzinfo=pytz.UTC),
            block_type="done",
        )
        b = BlockFactory(
            user=self.user,
            page=self.page,
            completed_at=datetime(2026, 4, 24, 11, 0, tzinfo=pytz.UTC),
            block_type="done",
        )
        out = self.run_query(
            {"completed_at": {"gte": "today"}},
            sort=[{"field": "completed_at", "dir": "desc"}],
        )
        self.assertEqual([blk.id for blk in out], [b.id, a.id])

    def test_unknown_sort_field_rejected(self):
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile(
                {}, user=self.user, sort=[{"field": "uuid", "dir": "asc"}]
            )


class TopLevelTests(_EngineTestBase):
    def test_empty_filter_matches_all(self):
        BlockFactory(user=self.user, page=self.page)
        BlockFactory(user=self.user, page=self.page)
        out = self.run_query({})
        self.assertEqual(len(out), 2)

    def test_user_scoping(self):
        BlockFactory(user=self.user, page=self.page, block_type="todo")
        other_page = PageFactory(user=self.other_user, page_type="page", title="OP")
        BlockFactory(user=self.other_user, page=other_page, block_type="todo")
        out = self.run_query({"block_type": "todo"})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].user_id, self.user.id)

    def test_unknown_field_rejected(self):
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile({"never_heard_of_it": 1}, user=self.user)

    def test_multi_key_object_rejected(self):
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile({"block_type": "todo", "has_tag": "x"}, user=self.user)

    def test_combinator_empty_list_rejected(self):
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile({"all": []}, user=self.user)
