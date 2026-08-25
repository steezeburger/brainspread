"""Shared resolve-view → compile → fetch pipeline.

Both surfaces that execute a SavedView — the run-view API command and the
automations engine — need the same sequence: look the view up, compile its
filter, fetch ``limit + 1`` rows so the caller can tell whether the result
was truncated. Keeping it here stops the two paths drifting (issue #143
review). Raises ``query_engine.QueryEngineError`` for a bad filter spec;
returns ``(None, [], False)`` when the view doesn't exist — callers decide
how to surface each.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional, Tuple

from ..models import Block, SavedView
from ..repositories import BlockRepository, SavedViewRepository
from . import query_engine


def _compile(user, view: SavedView, context_date: Optional[date]):
    return query_engine.compile(
        view.filter,
        user=user,
        sort=view.sort,
        context_date=context_date,
    )


def run_view(
    user,
    view: SavedView,
    *,
    limit: int,
    context_date: Optional[date] = None,
) -> Tuple[List[Block], bool]:
    """Execute an already-resolved view. Returns ``(blocks, truncated)``:
    at most ``limit`` rows, with ``truncated`` True when the view matched
    more."""
    compiled = _compile(user, view, context_date)
    rows = list(BlockRepository.run_compiled_query(user, compiled, limit=limit + 1))
    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]
    return rows, truncated


def count_view(
    user,
    view: SavedView,
    *,
    limit: int,
    context_date: Optional[date] = None,
) -> Tuple[int, bool]:
    """Count an already-resolved view's matches without fetching rows.
    Returns ``(count, truncated)`` with ``count`` capped at ``limit`` —
    the cheap path for collapsed embeds that only render a header
    number."""
    compiled = _compile(user, view, context_date)
    matched = BlockRepository.count_compiled_query(user, compiled, limit=limit + 1)
    return min(matched, limit), matched > limit


def run_filter(
    user,
    filter_spec: dict,
    *,
    limit: int,
    sort: Optional[list] = None,
    context_date: Optional[date] = None,
) -> Tuple[List[Block], bool]:
    """Execute a raw query-engine filter dict (automation inline queries,
    the run_query AI tool). Same ``(blocks, truncated)`` contract as
    ``run_view``; without ``sort`` the engine's default ordering
    applies."""
    compiled = query_engine.compile(
        filter_spec,
        user=user,
        sort=sort,
        context_date=context_date,
    )
    rows = list(BlockRepository.run_compiled_query(user, compiled, limit=limit + 1))
    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]
    return rows, truncated


def count_filter(
    user,
    filter_spec: dict,
    *,
    context_date: Optional[date] = None,
) -> int:
    """Count the blocks a raw filter dict matches, without fetching
    rows — the ``{{count:<query>}}`` content token (issue #140), which
    freezes an exact number into block content at resolve time."""
    compiled = query_engine.compile(
        filter_spec,
        user=user,
        context_date=context_date,
    )
    return BlockRepository.count_compiled_query(user, compiled)


def resolve_and_run_view(
    user,
    *,
    limit: int,
    view_slug: Optional[str] = None,
    view_uuid: Optional[str] = None,
    context_date: Optional[date] = None,
) -> Tuple[Optional[SavedView], List[Block], bool]:
    """Look the view up by slug/uuid and execute it. ``view`` is None
    (with empty results) when nothing matches."""
    view = (
        SavedViewRepository.get_by_uuid(str(view_uuid), user=user)
        if view_uuid
        else SavedViewRepository.get_by_slug(view_slug, user=user)
    )
    if view is None:
        return None, [], False
    blocks, truncated = run_view(user, view, limit=limit, context_date=context_date)
    return view, blocks, truncated
