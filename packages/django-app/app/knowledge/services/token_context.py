"""Django-aware wiring for the content token resolver (issue #140).

``content_tokens`` stays pure — this module is where the resolver's
context meets the real world: the user's clock/timezone, the target
page, the query engine behind ``{{count:<query>}}``, and the user's
custom variables (issue #228). Commands call
``build_token_context`` once per resolution pass (one block save, or
one whole template apply) and hand the result to
``resolve_content_tokens``.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterator, Mapping, Optional

from django.utils import timezone

from ..repositories import CustomVariableRepository
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
        custom_tokens=_LazyCustomVariables(user),
    )


def build_automation_token_context(
    user, *, match_count: Optional[int] = None
) -> TokenContext:
    """Ambient context for resolving an automation's action args (issue
    #209): ``{{today}}`` / ``{{now}}`` / bare ``{{count}}`` — resolved
    once per run, before any per-block or per-item scope is entered.

    No real page is in scope for an automation run (matched blocks can
    span many pages), and the automation consumer's restricted vocabulary
    (``automation_actions.AUTOMATION_TOKEN_VOCABULARY``) never reads
    ``page.*``/``user.*``/``uuid``/``input``/``count:<query>`` anyway, so
    ``page`` is a neutral placeholder and ``count_query``/``inputs`` stay
    unset — those tokens fail loudly (per the vocabulary check) rather
    than silently resolving to something meaningless.
    """
    now = timezone.now().astimezone(user.tz())
    return TokenContext(
        now=now,
        today=now.date(),
        user=UserTokenContext(
            email=user.email,
            timezone=user.timezone or "UTC",
            time_format=user.time_format or "24h",
        ),
        page=PageTokenContext(title="", slug="", uuid="", date=None, url=""),
        match_count=match_count,
    )


class _LazyCustomVariables(Mapping[str, str]):
    """Loads the user's custom variables on first lookup, so a save
    whose content has no ``{{`` never pays for the query."""

    def __init__(self, user) -> None:
        self._user = user
        self._data: Optional[Dict[str, str]] = None

    def _load(self) -> Dict[str, str]:
        if self._data is None:
            self._data = CustomVariableRepository.expansions_for_user(self._user)
        return self._data

    def __getitem__(self, key: str) -> str:
        return self._load()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._load())

    def __len__(self) -> int:
        return len(self._load())


def _make_count_query(user) -> Callable[[str], int]:
    def count(query_text: str) -> int:
        filter_spec = compile_inline_query(query_text)
        return count_filter(user, filter_spec, context_date=user.today())

    return count
