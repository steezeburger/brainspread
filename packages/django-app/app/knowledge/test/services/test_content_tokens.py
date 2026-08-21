from datetime import date, datetime
from typing import Optional

from django.test import SimpleTestCase

from knowledge.services.content_tokens import (
    FILTER_VOCABULARY,
    TOKEN_VOCABULARY,
    PageTokenContext,
    TokenContext,
    TokenError,
    UserTokenContext,
    find_input_tokens,
    resolve_content_tokens,
)


def make_context(
    *,
    now: Optional[datetime] = None,
    time_format: str = "24h",
    inputs=None,
    count_query=None,
    page_date: Optional[date] = None,
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
