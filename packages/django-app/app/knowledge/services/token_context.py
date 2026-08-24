"""Django-aware wiring for the content token resolver (issue #140).

``content_tokens`` stays pure — this module is where the resolver's
context meets the real world: the user's clock/timezone, the target
page, and the query engine behind ``{{count:<query>}}``. Commands call
``build_token_context`` once per resolution pass (one block save, or
one whole template apply) and hand the result to
``resolve_content_tokens``.
"""

from __future__ import annotations

from typing import Callable, Mapping, Optional

from django.utils import timezone

from .content_tokens import PageTokenContext, TokenContext, UserTokenContext
from .query_dsl import compile_inline_query
from .view_execution import count_filter


def build_token_context(
    user,
    page,
    *,
    inputs: Optional[Mapping[str, str]] = None,
) -> TokenContext:
    """Context for resolving tokens written on ``page`` by ``user``.

    ``inputs`` is None at block save (input tokens can't be answered
    there) and a label→value mapping at template apply."""
    now = timezone.now().astimezone(user.tz())
    return TokenContext(
        now=now,
        today=now.date(),
        user=UserTokenContext(
            email=user.email,
            timezone=user.timezone or "UTC",
            time_format=user.time_format or "24h",
        ),
        page=PageTokenContext(
            title=page.title,
            slug=page.slug,
            uuid=str(page.uuid),
            date=page.date,
            url=f"/knowledge/page/{page.slug}/",
        ),
        inputs=inputs,
        count_query=_make_count_query(user),
    )


def _make_count_query(user) -> Callable[[str], int]:
    def count(query_text: str) -> int:
        filter_spec = compile_inline_query(query_text)
        return count_filter(user, filter_spec, context_date=user.today())

    return count
