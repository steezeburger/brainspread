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

    def test_block_on_page_matches_without_explicit_tag(self):
        """Page-membership counts as an implicit tag — a block on page foo
        matches ``has_tag: foo`` even without an explicit M2M row."""
        foo = PageFactory(user=self.user, slug="foo", title="Foo")
        on_foo = BlockFactory(user=self.user, page=foo)
        BlockFactory(user=self.user, page=self.page)  # not on foo, untagged
        out = self.run_query({"has_tag": "foo"})
        self.assertEqual([b.id for b in out], [on_foo.id])

    def test_page_membership_unions_with_m2m_under_or(self):
        """A block on page foo and a block tagged #foo from another page
        both come back from a single ``has_tag: foo``."""
        foo = PageFactory(user=self.user, slug="foo", title="Foo")
        on_foo = BlockFactory(user=self.user, page=foo)
        tagged = BlockFactory(user=self.user, page=self.page)
        tagged.pages.add(foo)
        out = self.run_query({"has_tag": "foo"})
        self.assertEqual({b.id for b in out}, {on_foo.id, tagged.id})

    def test_page_membership_isolated_per_user(self):
        """Cross-user isolation also holds for the page-membership path —
        another user's block on their own ``foo`` page must not leak."""
        my_foo = PageFactory(user=self.user, slug="foo", title="Mine")
        my_block = BlockFactory(user=self.user, page=my_foo)
        their_foo = PageFactory(user=self.other_user, slug="foo", title="Theirs")
        BlockFactory(user=self.other_user, page=their_foo)
        out = self.run_query({"has_tag": "foo"})
        self.assertEqual([b.id for b in out], [my_block.id])

    def test_multi_tag_AND_with_page_membership(self):
        """A block on page foo that's also tagged #bar should match
        ``all: [has_tag foo, has_tag bar]``. This is the user's
        mental model: the home page contributes its slug as if it
        were an explicit tag."""
        foo = PageFactory(user=self.user, slug="foo", title="Foo")
        bar = PageFactory(user=self.user, slug="bar", title="Bar")
        match = BlockFactory(user=self.user, page=foo)
        match.pages.add(bar)
        # Block on foo without #bar → must not match.
        BlockFactory(user=self.user, page=foo)
        out = self.run_query({"all": [{"has_tag": "foo"}, {"has_tag": "bar"}]})
        self.assertEqual([b.id for b in out], [match.id])


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
    def test_value_shorthand_match(self):
        """Legacy ``{"key": K, "value": V}`` shape — kept working so old
        saved views (and the SavedViewsPage chip-prefill) still compile."""
        a = BlockFactory(
            user=self.user, page=self.page, properties={"priority": "high"}
        )
        BlockFactory(user=self.user, page=self.page, properties={"priority": "low"})
        out = self.run_query({"property_eq": {"key": "priority", "value": "high"}})
        self.assertEqual([b.id for b in out], [a.id])

    def test_eq_op_match(self):
        a = BlockFactory(
            user=self.user, page=self.page, properties={"priority": "high"}
        )
        BlockFactory(user=self.user, page=self.page, properties={"priority": "low"})
        out = self.run_query({"property_eq": {"key": "priority", "eq": "high"}})
        self.assertEqual([b.id for b in out], [a.id])

    def test_ne_excludes_match_but_not_missing(self):
        """``ne`` matches blocks with the key set to anything else — but
        *not* blocks without the key (SQL ``NULL <> 'x'`` is NULL)."""
        a = BlockFactory(
            user=self.user, page=self.page, properties={"priority": "high"}
        )
        BlockFactory(user=self.user, page=self.page, properties={"priority": "low"})
        BlockFactory(user=self.user, page=self.page, properties={})  # no priority
        out = self.run_query({"property_eq": {"key": "priority", "ne": "low"}})
        self.assertEqual([b.id for b in out], [a.id])

    def test_in_op(self):
        a = BlockFactory(
            user=self.user, page=self.page, properties={"priority": "high"}
        )
        b = BlockFactory(
            user=self.user, page=self.page, properties={"priority": "critical"}
        )
        BlockFactory(user=self.user, page=self.page, properties={"priority": "low"})
        out = self.run_query(
            {"property_eq": {"key": "priority", "in": ["high", "critical"]}}
        )
        self.assertEqual({blk.id for blk in out}, {a.id, b.id})

    def test_not_in_op(self):
        a = BlockFactory(
            user=self.user, page=self.page, properties={"priority": "high"}
        )
        BlockFactory(user=self.user, page=self.page, properties={"priority": "low"})
        BlockFactory(user=self.user, page=self.page, properties={"priority": "trivial"})
        out = self.run_query(
            {"property_eq": {"key": "priority", "not_in": ["low", "trivial"]}}
        )
        self.assertEqual([blk.id for blk in out], [a.id])

    def test_contains_icontains(self):
        a = BlockFactory(user=self.user, page=self.page, properties={"area": "Health"})
        BlockFactory(user=self.user, page=self.page, properties={"area": "Work"})
        out = self.run_query({"property_eq": {"key": "area", "contains": "heal"}})
        self.assertEqual([blk.id for blk in out], [a.id])

    def test_starts_with(self):
        a = BlockFactory(
            user=self.user, page=self.page, properties={"project": "roadmap-q1"}
        )
        BlockFactory(
            user=self.user, page=self.page, properties={"project": "ops-roadmap"}
        )
        out = self.run_query(
            {"property_eq": {"key": "project", "starts_with": "roadmap"}}
        )
        self.assertEqual([blk.id for blk in out], [a.id])

    def test_ends_with(self):
        a = BlockFactory(user=self.user, page=self.page, properties={"file": "a.md"})
        BlockFactory(user=self.user, page=self.page, properties={"file": "a.txt"})
        out = self.run_query({"property_eq": {"key": "file", "ends_with": ".md"}})
        self.assertEqual([blk.id for blk in out], [a.id])

    def test_lt_lexicographic(self):
        """String comparison on ISO date-shaped values — useful for
        ``due:: 2026-05-01`` until typed properties land."""
        a = BlockFactory(
            user=self.user, page=self.page, properties={"due": "2026-04-30"}
        )
        BlockFactory(user=self.user, page=self.page, properties={"due": "2026-05-05"})
        out = self.run_query({"property_eq": {"key": "due", "lt": "2026-05-01"}})
        self.assertEqual([blk.id for blk in out], [a.id])

    def test_range_with_gte_and_lte(self):
        a = BlockFactory(
            user=self.user, page=self.page, properties={"due": "2026-05-03"}
        )
        BlockFactory(user=self.user, page=self.page, properties={"due": "2026-04-30"})
        BlockFactory(user=self.user, page=self.page, properties={"due": "2026-05-10"})
        out = self.run_query(
            {
                "property_eq": {
                    "key": "due",
                    "gte": "2026-05-01",
                    "lte": "2026-05-05",
                }
            }
        )
        self.assertEqual([blk.id for blk in out], [a.id])

    def test_missing_ops_rejected(self):
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile({"property_eq": {"key": "priority"}}, user=self.user)

    def test_value_and_eq_collision_rejected(self):
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile(
                {"property_eq": {"key": "priority", "value": "high", "eq": "low"}},
                user=self.user,
            )

    def test_unknown_op_rejected(self):
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile(
                {"property_eq": {"key": "priority", "like": "high"}}, user=self.user
            )

    def test_in_empty_list_rejected(self):
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile(
                {"property_eq": {"key": "priority", "in": []}}, user=self.user
            )

    def test_bad_key_charset_rejected(self):
        """Keys are constrained to the parser's charset so query keys
        match what the inline ``key:: value`` parser will actually
        produce — spaces, dots, slashes etc. never appear in real blocks."""
        for bad_key in ("with space", "priority.x", "key/foo", "k;drop"):
            with self.assertRaises(query_engine.QueryEngineError):
                query_engine.compile(
                    {"property_eq": {"key": bad_key, "eq": "high"}},
                    user=self.user,
                )


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


class NotCombinatorTests(_EngineTestBase):
    """Negation — ``{"not": <node>}`` wraps any subspec with ~Q.

    The headline use case is "Glitch's favorites without Jesse": a
    block tagged with #glitch and #favorite-things, but not #jesse.
    Without ``not``, callers can't express AND-with-exclusions in the
    saved-view JSON.
    """

    def test_not_excludes_tagged(self):
        glitch = PageFactory(user=self.user, slug="glitch", title="Glitch")
        favs = PageFactory(user=self.user, slug="favorite-things", title="Favs")
        jesse = PageFactory(user=self.user, slug="jesse", title="Jesse")

        glitch_only = BlockFactory(user=self.user, page=self.page)
        glitch_only.pages.add(glitch)
        glitch_only.pages.add(favs)

        glitch_and_jesse = BlockFactory(user=self.user, page=self.page)
        glitch_and_jesse.pages.add(glitch)
        glitch_and_jesse.pages.add(favs)
        glitch_and_jesse.pages.add(jesse)

        out = self.run_query(
            {
                "all": [
                    {"has_tag": "glitch"},
                    {"has_tag": "favorite-things"},
                    {"not": {"has_tag": "jesse"}},
                ]
            }
        )
        self.assertEqual([b.id for b in out], [glitch_only.id])

    def test_not_negates_block_type(self):
        a = BlockFactory(user=self.user, page=self.page, block_type="todo")
        BlockFactory(user=self.user, page=self.page, block_type="bullet")
        out = self.run_query({"not": {"block_type": "bullet"}})
        # Among blocks the user owns, the only non-bullet block is `a`.
        self.assertEqual({b.id for b in out}, {a.id})

    def test_double_negation_is_noop(self):
        """``not(not(X))`` should match the same set as ``X``."""
        glitch = PageFactory(user=self.user, slug="glitch", title="Glitch")
        match = BlockFactory(user=self.user, page=self.page)
        match.pages.add(glitch)
        BlockFactory(user=self.user, page=self.page)  # untagged
        out_double = self.run_query({"not": {"not": {"has_tag": "glitch"}}})
        out_plain = self.run_query({"has_tag": "glitch"})
        self.assertEqual([b.id for b in out_double], [b.id for b in out_plain])

    def test_not_requires_dict_value(self):
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile({"not": []}, user=self.user)
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile({"not": {}}, user=self.user)
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile({"not": "glitch"}, user=self.user)


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

    def test_sort_by_property_asc(self):
        """``properties.<key>`` sorts by JSONB value. Strings compare
        lexicographically, so a/b/c ordering is by raw string."""
        b = BlockFactory(user=self.user, page=self.page, properties={"priority": "b"})
        a = BlockFactory(user=self.user, page=self.page, properties={"priority": "a"})
        c = BlockFactory(user=self.user, page=self.page, properties={"priority": "c"})
        out = self.run_query(
            {"has_property": "priority"},
            sort=[{"field": "properties.priority", "dir": "asc"}],
        )
        self.assertEqual([blk.id for blk in out], [a.id, b.id, c.id])

    def test_sort_by_property_desc(self):
        b = BlockFactory(user=self.user, page=self.page, properties={"priority": "b"})
        a = BlockFactory(user=self.user, page=self.page, properties={"priority": "a"})
        c = BlockFactory(user=self.user, page=self.page, properties={"priority": "c"})
        out = self.run_query(
            {"has_property": "priority"},
            sort=[{"field": "properties.priority", "dir": "desc"}],
        )
        self.assertEqual([blk.id for blk in out], [c.id, b.id, a.id])

    def test_sort_property_bad_key_rejected(self):
        for bad_field in (
            "properties.with space",
            "properties.priority.nested",
            "properties.k/x",
        ):
            with self.assertRaises(query_engine.QueryEngineError):
                query_engine.compile(
                    {}, user=self.user, sort=[{"field": bad_field, "dir": "asc"}]
                )

    def test_sort_property_empty_key_rejected(self):
        with self.assertRaises(query_engine.QueryEngineError):
            query_engine.compile(
                {}, user=self.user, sort=[{"field": "properties.", "dir": "asc"}]
            )

    def test_default_sort_is_newest_first(self):
        """When the spec omits sort, the repository falls back to
        ``-created_at`` (newest first). This pins the contract so the
        default doesn't drift back to ``scheduled_for`` (which felt
        random for tag-only views that have no dates)."""
        import time

        older = BlockFactory(user=self.user, page=self.page, content="older")
        time.sleep(0.01)  # auto_now_add timestamps are precise enough that
        # a tight loop can land two blocks in the same microsecond on fast
        # boxes; a 10ms sleep keeps the order assertion deterministic.
        newer = BlockFactory(user=self.user, page=self.page, content="newer")
        out = self.run_query({})  # no sort
        self.assertEqual([b.id for b in out], [newer.id, older.id])


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
