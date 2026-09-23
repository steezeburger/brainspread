from datetime import date, datetime
from typing import Optional

from django.test import SimpleTestCase

from knowledge.services.content_tokens import (
    BUILTIN_TOKEN_NAMES,
    FILTER_VOCABULARY,
    MAX_CUSTOM_TOKEN_DEPTH,
    TOKEN_VOCABULARY,
    BlockTokenAmbiguousError,
    BlockTokenContext,
    PageTokenContext,
    TokenContext,
    TokenError,
    UserTokenContext,
    find_custom_token_cycle,
    find_input_tokens,
    resolve_content_tokens,
    token_names,
)


def make_context(
    *,
    now: Optional[datetime] = None,
    time_format: str = "24h",
    inputs=None,
    count_query=None,
    page_date: Optional[date] = None,
    custom_tokens=None,
    match_count=None,
    item=None,
    block: Optional[BlockTokenContext] = None,
) -> TokenContext:
    now = now or datetime(2026, 8, 21, 14, 32)
    uuid_counter = iter(range(1, 100))
    return TokenContext(
        now=now,
        today=now.date(),
        user=UserTokenContext(
            email="ada@example.com",
            timezone="America/Denver",
            time_format=time_format,
        ),
        page=PageTokenContext(
            title="Weekly Review",
            slug="weekly-review",
            uuid="page-uuid-1",
            date=page_date,
            url="/knowledge/page/weekly-review/",
        ),
        inputs=inputs,
        count_query=count_query,
        uuid_factory=lambda: f"uuid-{next(uuid_counter)}",
        custom_tokens=custom_tokens or {},
        match_count=match_count,
        item=item,
        block=block,
    )


def make_block(
    *,
    tags=(),
    content="",
    uuid="block-uuid-1",
    page="Inbox",
    due="",
) -> BlockTokenContext:
    return BlockTokenContext(
        tag_candidates=tuple(tags), content=content, uuid=uuid, page=page, due=due
    )


class TestDateTimeTokens(SimpleTestCase):
    def test_date_tokens_freeze_iso_dates(self):
        ctx = make_context()
        self.assertEqual(resolve_content_tokens("{{today}}", ctx), "2026-08-21")
        self.assertEqual(resolve_content_tokens("{{tomorrow}}", ctx), "2026-08-22")
        self.assertEqual(resolve_content_tokens("{{yesterday}}", ctx), "2026-08-20")

    def test_now_renders_date_and_time(self):
        self.assertEqual(
            resolve_content_tokens("{{now}}", make_context()),
            "2026-08-21 14:32",
        )
        self.assertEqual(
            resolve_content_tokens("{{now}}", make_context(time_format="12h")),
            "2026-08-21 2:32pm",
        )

    def test_current_date_and_current_time_aliases(self):
        ctx = make_context(time_format="12h")
        self.assertEqual(resolve_content_tokens("{{current_date}}", ctx), "2026-08-21")
        self.assertEqual(resolve_content_tokens("{{current_time}}", ctx), "2:32pm")
        self.assertEqual(
            resolve_content_tokens("{{current_time}}", make_context()), "14:32"
        )

    def test_twelve_hour_edges(self):
        midnight = make_context(now=datetime(2026, 8, 21, 0, 5), time_format="12h")
        noon = make_context(now=datetime(2026, 8, 21, 12, 5), time_format="12h")
        self.assertEqual(
            resolve_content_tokens("{{current_time}}", midnight), "12:05am"
        )
        self.assertEqual(resolve_content_tokens("{{current_time}}", noon), "12:05pm")

    def test_tokens_resolve_inside_prose(self):
        ctx = make_context(time_format="12h")
        self.assertEqual(
            resolve_content_tokens("cup of yogurt @ {{current_time}} #food-log", ctx),
            "cup of yogurt @ 2:32pm #food-log",
        )


class TestFilters(SimpleTestCase):
    def test_date_filter_truncates_now(self):
        self.assertEqual(
            resolve_content_tokens("{{now|date}}", make_context()), "2026-08-21"
        )

    def test_time_filter_on_now(self):
        self.assertEqual(
            resolve_content_tokens("{{now|time}}", make_context()), "14:32"
        )

    def test_time_filter_rejects_pure_dates(self):
        with self.assertRaises(TokenError):
            resolve_content_tokens("{{today|time}}", make_context())

    def test_format_filter_strftime(self):
        self.assertEqual(
            resolve_content_tokens("{{today|format:%b %d, %Y}}", make_context()),
            "Aug 21, 2026",
        )

    def test_filters_chain(self):
        self.assertEqual(
            resolve_content_tokens("{{now|date|format:%d.%m.%Y}}", make_context()),
            "21.08.2026",
        )

    def test_unknown_filter_fails_loudly(self):
        with self.assertRaises(TokenError) as caught:
            resolve_content_tokens("{{today|shout}}", make_context())
        for fname in FILTER_VOCABULARY:
            self.assertIn(fname, str(caught.exception))

    def test_format_filter_rejects_strings(self):
        with self.assertRaises(TokenError):
            resolve_content_tokens("{{page.title|format:%Y}}", make_context())


class TestContextTokens(SimpleTestCase):
    def test_page_tokens(self):
        ctx = make_context(page_date=date(2026, 8, 17))
        self.assertEqual(
            resolve_content_tokens(
                "{{page.title}} / {{page.slug}} / {{page.uuid}} / "
                "{{page.date}} / {{page.url}}",
                ctx,
            ),
            "Weekly Review / weekly-review / page-uuid-1 / "
            "2026-08-17 / /knowledge/page/weekly-review/",
        )

    def test_page_date_empty_when_page_has_none(self):
        self.assertEqual(
            resolve_content_tokens("d:{{page.date}}", make_context()), "d:"
        )

    def test_user_tokens(self):
        self.assertEqual(
            resolve_content_tokens(
                "{{user.email}} ({{user.timezone}})", make_context()
            ),
            "ada@example.com (America/Denver)",
        )


class TestUuidAndCursor(SimpleTestCase):
    def test_bare_uuid_is_fresh_per_occurrence(self):
        self.assertEqual(
            resolve_content_tokens("{{uuid}} {{uuid}}", make_context()),
            "uuid-1 uuid-2",
        )

    def test_named_uuid_is_stable_across_occurrences_and_calls(self):
        ctx = make_context()
        first = resolve_content_tokens("{{uuid|name:cart}}", ctx)
        second = resolve_content_tokens(
            "link:: {{uuid|name:cart}} other:: {{uuid|name:proj}}", ctx
        )
        self.assertEqual(first, "uuid-1")
        self.assertEqual(second, "link:: uuid-1 other:: uuid-2")

    def test_name_filter_requires_uuid_base(self):
        with self.assertRaises(TokenError):
            resolve_content_tokens("{{today|name:cart}}", make_context())

    def test_name_filter_requires_label(self):
        with self.assertRaises(TokenError):
            resolve_content_tokens("{{uuid|name}}", make_context())

    def test_cursor_resolves_away(self):
        self.assertEqual(
            resolve_content_tokens("start {{cursor}}end", make_context()),
            "start end",
        )


class TestInputTokens(SimpleTestCase):
    def test_input_resolves_from_provided_values(self):
        ctx = make_context(inputs={"name": "Q3 launch"})
        self.assertEqual(
            resolve_content_tokens("Project {{input:name}}", ctx),
            "Project Q3 launch",
        )

    def test_input_fails_where_prompting_is_impossible(self):
        with self.assertRaises(TokenError) as caught:
            resolve_content_tokens("{{input:name}}", make_context())
        self.assertIn("applying a template", str(caught.exception))

    def test_input_fails_when_value_missing(self):
        with self.assertRaises(TokenError):
            resolve_content_tokens(
                "{{input:name}}", make_context(inputs={"other": "x"})
            )

    def test_input_requires_label(self):
        with self.assertRaises(TokenError):
            resolve_content_tokens("{{input}}", make_context(inputs={}))

    def test_find_input_tokens_ordered_and_deduplicated(self):
        labels = find_input_tokens(
            "a {{input:name}} b {{input:goal}} c {{input:name}} "
            "d \\{{input:escaped}} e {{today}}"
        )
        self.assertEqual(labels, ["name", "goal"])

    def test_find_input_tokens_allows_spaced_labels(self):
        self.assertEqual(find_input_tokens("{{input:Project Name}}"), ["Project Name"])


class TestCountTokens(SimpleTestCase):
    def test_count_calls_injected_query(self):
        seen = []

        def fake_count(query: str) -> int:
            seen.append(query)
            return 7

        ctx = make_context(count_query=fake_count)
        self.assertEqual(
            resolve_content_tokens(
                "Open going into the week: "
                "{{count:type:todo and completed is null}}",
                ctx,
            ),
            "Open going into the week: 7",
        )
        self.assertEqual(seen, ["type:todo and completed is null"])

    def test_count_query_error_names_the_token(self):
        def bad_count(query: str) -> int:
            raise ValueError("unknown predicate `nope:`")

        with self.assertRaises(TokenError) as caught:
            resolve_content_tokens(
                "{{count:nope:x}}", make_context(count_query=bad_count)
            )
        self.assertIn("{{count:nope:x}}", str(caught.exception))
        self.assertIn("unknown predicate", str(caught.exception))

    def test_count_requires_query(self):
        with self.assertRaises(TokenError):
            resolve_content_tokens("{{count}}", make_context(count_query=len))


class TestErrorsAndEscaping(SimpleTestCase):
    def test_unknown_token_lists_vocabulary(self):
        with self.assertRaises(TokenError) as caught:
            resolve_content_tokens("{{blorp}}", make_context())
        message = str(caught.exception)
        self.assertIn("{{blorp}}", message)
        for name in TOKEN_VOCABULARY:
            self.assertIn(name, message)

    def test_arg_on_argless_token_fails(self):
        with self.assertRaises(TokenError):
            resolve_content_tokens("{{today:tomorrow}}", make_context())

    def test_empty_token_fails(self):
        with self.assertRaises(TokenError):
            resolve_content_tokens("{{}}", make_context())

    def test_escaped_braces_stay_literal(self):
        self.assertEqual(
            resolve_content_tokens("\\{{today}} is a token", make_context()),
            "{{today}} is a token",
        )

    def test_unclosed_braces_are_plain_text(self):
        ctx = make_context()
        self.assertEqual(resolve_content_tokens("a {{ b", ctx), "a {{ b")
        self.assertEqual(resolve_content_tokens("{{today", ctx), "{{today")

    def test_tokens_do_not_span_lines(self):
        text = "{{to\nday}}"
        self.assertEqual(resolve_content_tokens(text, make_context()), text)

    def test_text_without_tokens_is_untouched(self):
        text = "no tokens here } { at all"
        self.assertEqual(resolve_content_tokens(text, make_context()), text)

    def test_empty_content_passes_through(self):
        self.assertEqual(resolve_content_tokens("", make_context()), "")


class TestCustomVariables(SimpleTestCase):
    """User-defined tokens (issue #228): recursive, cycle-safe expansion."""

    def test_plain_custom_variable_expands(self):
        ctx = make_context(custom_tokens={"stack": "sabroxy, tongkat"})
        self.assertEqual(
            resolve_content_tokens("took {{stack}}", ctx), "took sabroxy, tongkat"
        )

    def test_builtin_inside_custom_variable_resolves(self):
        ctx = make_context(
            custom_tokens={"time_and_food_log": "{{current_time}} #food-log"}
        )
        self.assertEqual(
            resolve_content_tokens("{{time_and_food_log}} eggs", ctx),
            "14:32 #food-log eggs",
        )

    def test_custom_variable_inside_custom_variable_resolves(self):
        ctx = make_context(
            custom_tokens={
                "stack": "sabroxy, tongkat, omegaTAU",
                "daily_mood_stack_log": "{{stack}} @ {{current_time}} #supplements",
            }
        )
        self.assertEqual(
            resolve_content_tokens("{{daily_mood_stack_log}}", ctx),
            "sabroxy, tongkat, omegaTAU @ 14:32 #supplements",
        )

    def test_name_is_case_insensitive(self):
        ctx = make_context(custom_tokens={"stack": "x"})
        self.assertEqual(resolve_content_tokens("{{ Stack }}", ctx), "x")

    def test_escaped_braces_in_expansion_stay_literal(self):
        ctx = make_context(custom_tokens={"lit": "\\{{today}}"})
        self.assertEqual(resolve_content_tokens("{{lit}}", ctx), "{{today}}")

    def test_builtin_wins_over_same_named_custom_variable(self):
        ctx = make_context(custom_tokens={"today": "shadowed"})
        self.assertEqual(resolve_content_tokens("{{today}}", ctx), "2026-08-21")

    def test_self_reference_raises_naming_cycle(self):
        ctx = make_context(custom_tokens={"a": "x {{a}}"})
        with self.assertRaises(TokenError) as cm:
            resolve_content_tokens("{{a}}", ctx)
        self.assertIn("a → a", str(cm.exception))

    def test_mutual_reference_raises_naming_cycle(self):
        ctx = make_context(custom_tokens={"a": "{{b}}", "b": "{{a}}"})
        with self.assertRaises(TokenError) as cm:
            resolve_content_tokens("start {{a}}", ctx)
        self.assertIn("a → b → a", str(cm.exception))

    def test_cycle_entered_mid_chain_names_only_the_loop(self):
        ctx = make_context(custom_tokens={"top": "{{a}}", "a": "{{b}}", "b": "{{a}}"})
        with self.assertRaises(TokenError) as cm:
            resolve_content_tokens("{{top}}", ctx)
        self.assertIn("cycle: a → b → a", str(cm.exception))

    def test_depth_cap_stops_long_acyclic_chains(self):
        depth = MAX_CUSTOM_TOKEN_DEPTH + 1
        tokens = {f"v{i}": f"{{{{v{i + 1}}}}}" for i in range(depth)}
        tokens[f"v{depth}"] = "end"
        with self.assertRaises(TokenError) as cm:
            resolve_content_tokens("{{v0}}", make_context(custom_tokens=tokens))
        self.assertIn("nested more than", str(cm.exception))

    def test_chain_at_depth_cap_resolves(self):
        depth = MAX_CUSTOM_TOKEN_DEPTH - 1
        tokens = {f"v{i}": f"{{{{v{i + 1}}}}}" for i in range(depth)}
        tokens[f"v{depth}"] = "end"
        self.assertEqual(
            resolve_content_tokens("{{v0}}", make_context(custom_tokens=tokens)),
            "end",
        )

    def test_unknown_token_error_lists_custom_variables(self):
        ctx = make_context(custom_tokens={"stack": "x"})
        with self.assertRaises(TokenError) as cm:
            resolve_content_tokens("{{nope}}", ctx)
        self.assertIn("your variables: stack", str(cm.exception))

    def test_unknown_token_inside_expansion_fails_loudly(self):
        ctx = make_context(custom_tokens={"broken": "{{nope}}"})
        with self.assertRaises(TokenError):
            resolve_content_tokens("{{broken}}", ctx)

    def test_find_input_tokens_looks_inside_custom_variables(self):
        tokens = {"ask": "{{input:Mood}}", "loop": "{{loop}} {{input:Loop}}"}
        self.assertEqual(
            find_input_tokens("{{input:Title}} {{ask}} {{loop}}", tokens),
            ["Title", "Mood", "Loop"],
        )

    def test_find_custom_token_cycle(self):
        tokens = {"a": "{{b}}", "b": "{{c}} {{today}}", "c": "{{a}}", "d": "{{a}}"}
        self.assertEqual(find_custom_token_cycle("a", tokens), ["a", "b", "c", "a"])
        self.assertIsNone(find_custom_token_cycle("d", tokens))
        self.assertIsNone(find_custom_token_cycle("x", {"x": "{{today}}"}))

    def test_builtin_names_are_bare(self):
        self.assertIn("input", BUILTIN_TOKEN_NAMES)
        self.assertIn("page.title", BUILTIN_TOKEN_NAMES)
        self.assertIn("current_time", BUILTIN_TOKEN_NAMES)


class TestAmbientMatchCount(SimpleTestCase):
    """Bare {{count}} (issue #209) — the automation's matched-block
    total, distinct from the existing {{count:<query>}} arg form."""

    def test_bare_count_reads_match_count(self):
        ctx = make_context(match_count=7)
        self.assertEqual(resolve_content_tokens("{{count}} left", ctx), "7 left")

    def test_bare_count_without_match_count_fails(self):
        with self.assertRaises(TokenError):
            resolve_content_tokens("{{count}}", make_context())

    def test_count_with_query_arg_still_uses_count_query(self):
        # match_count set (ambient) and an explicit :<query> arg both
        # present — the arg form still wins, unaffected by match_count.
        ctx = make_context(match_count=99, count_query=lambda q: 3 if q == "x" else 0)
        self.assertEqual(resolve_content_tokens("{{count:x}}", ctx), "3")

    def test_count_arg_without_count_query_fails(self):
        with self.assertRaises(TokenError):
            resolve_content_tokens("{{count:x}}", make_context(match_count=5))


class TestItemToken(SimpleTestCase):
    """{{item}} (issue #209) — bound during `for::` iteration."""

    def test_item_resolves_from_context(self):
        self.assertEqual(
            resolve_content_tokens("n={{item}}", make_context(item="10")), "n=10"
        )

    def test_item_without_for_iteration_fails(self):
        with self.assertRaises(TokenError) as cm:
            resolve_content_tokens("{{item}}", make_context())
        self.assertIn("for::", str(cm.exception))


class TestBlockTokens(SimpleTestCase):
    """{{block.*}} (issue #209) — resolved against TokenContext.block,
    one matched block at a time."""

    def test_block_tag_resolves_when_exactly_one_candidate(self):
        ctx = make_context(block=make_block(tags=["groceries"]))
        self.assertEqual(resolve_content_tokens("{{block.tag}}", ctx), "groceries")

    def test_block_content_strips_state_prefix_already(self):
        # BlockTokenContext.content arrives pre-stripped (the Django-aware
        # caller does the stripping) — the resolver just passes it through.
        ctx = make_context(block=make_block(content="ship it"))
        self.assertEqual(resolve_content_tokens("{{block.content}}", ctx), "ship it")

    def test_block_uuid_and_page(self):
        ctx = make_context(block=make_block(uuid="abc-123", page="Groceries"))
        self.assertEqual(
            resolve_content_tokens("{{block.uuid}} / {{block.page}}", ctx),
            "abc-123 / Groceries",
        )

    def test_block_due_resolves_or_empty(self):
        with_due = make_context(block=make_block(due="2026-09-01"))
        without_due = make_context(block=make_block(due=""))
        self.assertEqual(
            resolve_content_tokens("{{block.due}}", with_due), "2026-09-01"
        )
        self.assertEqual(resolve_content_tokens("d:{{block.due}}", without_due), "d:")

    def test_block_tokens_without_block_scope_fail(self):
        for token in (
            "{{block.tag}}",
            "{{block.content}}",
            "{{block.uuid}}",
            "{{block.page}}",
            "{{block.due}}",
        ):
            with self.assertRaises(TokenError, msg=token):
                resolve_content_tokens(token, make_context())

    def test_bare_block_tag_with_zero_candidates_is_ambiguous(self):
        ctx = make_context(block=make_block(tags=[]))
        with self.assertRaises(BlockTokenAmbiguousError) as cm:
            resolve_content_tokens("{{block.tag}}", ctx)
        self.assertIn("found 0", str(cm.exception))

    def test_bare_block_tag_with_multiple_candidates_is_ambiguous(self):
        ctx = make_context(block=make_block(tags=["groceries", "urgent"]))
        with self.assertRaises(BlockTokenAmbiguousError) as cm:
            resolve_content_tokens("{{block.tag}}", ctx)
        self.assertIn("found 2", str(cm.exception))

    def test_ambiguous_error_is_a_token_error_subclass(self):
        self.assertTrue(issubclass(BlockTokenAmbiguousError, TokenError))


class TestBlockTagExceptFilter(SimpleTestCase):
    def test_except_narrows_to_exactly_one(self):
        ctx = make_context(
            block=make_block(tags=["braindumps", "automation", "groceries"])
        )
        self.assertEqual(
            resolve_content_tokens("{{block.tag|except:braindumps,automation}}", ctx),
            "groceries",
        )

    def test_except_leaving_zero_is_still_ambiguous(self):
        ctx = make_context(block=make_block(tags=["braindumps"]))
        with self.assertRaises(BlockTokenAmbiguousError):
            resolve_content_tokens("{{block.tag|except:braindumps}}", ctx)

    def test_except_leaving_multiple_is_still_ambiguous(self):
        ctx = make_context(block=make_block(tags=["a", "b", "c"]))
        with self.assertRaises(BlockTokenAmbiguousError):
            resolve_content_tokens("{{block.tag|except:a}}", ctx)

    def test_except_only_applies_to_block_tag(self):
        with self.assertRaises(TokenError):
            resolve_content_tokens("{{today|except:x}}", make_context())

    def test_except_needs_at_least_one_slug(self):
        ctx = make_context(block=make_block(tags=["a"]))
        with self.assertRaises(TokenError):
            resolve_content_tokens("{{block.tag|except:}}", ctx)

    def test_bare_block_tag_has_no_builtin_exclusions(self):
        # Bare {{block.tag}} excludes nothing by default — not even
        # "automation" — so a block tagged only #automation still
        # resolves to exactly that one candidate.
        ctx = make_context(block=make_block(tags=["automation"]))
        self.assertEqual(resolve_content_tokens("{{block.tag}}", ctx), "automation")


class TestTokenNames(SimpleTestCase):
    def test_token_names_lists_base_names_in_order(self):
        self.assertEqual(
            token_names("{{today}} {{block.tag|except:x}} {{item}}"),
            ["today", "block.tag", "item"],
        )

    def test_token_names_skips_escaped_tokens(self):
        self.assertEqual(token_names("\\{{today}} {{now}}"), ["now"])

    def test_token_names_empty_for_plain_text(self):
        self.assertEqual(token_names("no tokens here"), [])
