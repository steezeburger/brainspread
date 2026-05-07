"""Structured filter → Django Q compiler for SavedView (issue #60).

The filter spec is JSON with two flavors of node:

- **Combinator**: ``{"all": [<node>, ...]}`` or ``{"any": [<node>, ...]}``
  combines child nodes under AND / OR.
- **Predicate**: ``{<field>: <value-or-op-dict>}`` where ``<field>`` is one
  of the supported predicate names. ``<value>`` is either a scalar
  shorthand (interpreted as ``eq``) or a dict of ``{op: arg, ...}``.

Supported predicates and their ops are listed in :data:`PREDICATE_HANDLERS`.
Date tokens (``today``, ``tomorrow``, ``yesterday``, ``N days ago``,
``N days from now``, ISO ``YYYY-MM-DD``) are resolved at execute time
against ``user.today()`` so views stay relative.

``has_tag`` compiles to an ``Exists()`` subquery against the Block.pages
through table, which makes multi-tag AND/OR composition Just Work under
arbitrary combinator nesting (a single ``filter(pages__slug__in=[...])``
would match *any* tag, not *all* — see issue #60's "Glitch's favorite
things" example for why this matters).

The engine deliberately does no DB I/O — it returns a ``CompiledQuery``
that the BlockRepository runs. Per the project's repository rule, all
``.filter()``/``.objects.filter()`` calls live in the repository layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Dict, List

from django.db.models import Exists, OuterRef, Q

from knowledge.models import Block

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class QueryEngineError(ValueError):
    """Raised when a filter / sort spec is malformed or references unknown
    fields / ops. Surfaces as a 400 in the API layer."""


# ---------------------------------------------------------------------------
# Compiled output
# ---------------------------------------------------------------------------


@dataclass
class CompiledQuery:
    """Output of :func:`compile`. The repository turns this into a queryset."""

    filter_q: Q
    order_by: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Date token resolution
# ---------------------------------------------------------------------------

_DAYS_AGO_RE = re.compile(r"^(\d+)\s+days?\s+ago$")
_DAYS_FROM_NOW_RE = re.compile(r"^(?:in\s+(\d+)\s+days?|(\d+)\s+days?\s+from\s+now)$")


def _resolve_date_token(raw: Any, user) -> date:
    """Turn a token (``"today"``, ``"3 days ago"``, ``"2026-05-01"``, or a
    ``date``/``datetime``) into a concrete date in the user's timezone."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str):
        raise QueryEngineError(
            f"Expected date string, got {type(raw).__name__}: {raw!r}"
        )

    s = raw.strip().lower()
    today = user.today()

    if s == "today":
        return today
    if s == "tomorrow":
        return today + timedelta(days=1)
    if s == "yesterday":
        return today - timedelta(days=1)

    m = _DAYS_AGO_RE.match(s)
    if m:
        return today - timedelta(days=int(m.group(1)))

    m = _DAYS_FROM_NOW_RE.match(s)
    if m:
        n = int(m.group(1) or m.group(2))
        return today + timedelta(days=n)

    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise QueryEngineError(f"Unrecognized date token: {raw!r}") from exc


def _start_of_local_day(d: date, user) -> datetime:
    """Aware datetime at midnight of d in the user's timezone. pytz needs
    ``localize()`` rather than ``tzinfo=`` to pick the right DST offset."""
    return user.tz().localize(datetime.combine(d, time.min))


# ---------------------------------------------------------------------------
# Predicate handlers
# ---------------------------------------------------------------------------

# Pulled from Block.block_type choices; refresh if the model gains new types.
_BLOCK_TYPES = {choice[0] for choice in Block._meta.get_field("block_type").choices}


def _block_type_q(value: Any, user) -> Q:
    if isinstance(value, str):
        value = {"eq": value}
    if not isinstance(value, dict):
        raise QueryEngineError(f"Invalid block_type predicate: {value!r}")

    q = Q()
    for op, arg in value.items():
        if op == "eq":
            if arg not in _BLOCK_TYPES:
                raise QueryEngineError(f"Unknown block_type: {arg!r}")
            q &= Q(block_type=arg)
        elif op == "in":
            if not isinstance(arg, list) or not arg:
                raise QueryEngineError(
                    f"block_type 'in' must be a non-empty list: {arg!r}"
                )
            unknown = [v for v in arg if v not in _BLOCK_TYPES]
            if unknown:
                raise QueryEngineError(f"Unknown block_type(s): {unknown!r}")
            q &= Q(block_type__in=arg)
        else:
            raise QueryEngineError(f"Unsupported op {op!r} on block_type")
    return q


def _date_field_q(field_name: str, value: Any, user, is_datetime: bool) -> Q:
    """Shared compiler for date / datetime predicates.

    DateField predicates compare directly. DateTimeField predicates
    (completed_at) anchor to user-local day boundaries: ``gte: <d>``
    becomes ``>= start of d (local)``, ``lt: <d>`` becomes ``< start of d``,
    ``lte: <d>`` becomes ``< start of next day``, and ``gt: <d>`` becomes
    ``>= start of next day``. ``between [a, b]`` is inclusive on both
    ends in user-local terms.
    """
    if isinstance(value, str) or isinstance(value, (date, datetime)):
        value = {"eq": value}
    if not isinstance(value, dict):
        raise QueryEngineError(f"Invalid {field_name} predicate: {value!r}")

    q = Q()
    for op, arg in value.items():
        if op == "is_null":
            if not isinstance(arg, bool):
                raise QueryEngineError(f"is_null must be bool: {arg!r}")
            q &= Q(**{f"{field_name}__isnull": arg})
        elif op == "eq":
            d = _resolve_date_token(arg, user)
            q &= _date_eq_q(field_name, d, user, is_datetime)
        elif op == "lt":
            d = _resolve_date_token(arg, user)
            if is_datetime:
                q &= Q(**{f"{field_name}__lt": _start_of_local_day(d, user)})
            else:
                q &= Q(**{f"{field_name}__lt": d})
        elif op == "lte":
            d = _resolve_date_token(arg, user)
            if is_datetime:
                next_day = _start_of_local_day(d + timedelta(days=1), user)
                q &= Q(**{f"{field_name}__lt": next_day})
            else:
                q &= Q(**{f"{field_name}__lte": d})
        elif op == "gt":
            d = _resolve_date_token(arg, user)
            if is_datetime:
                next_day = _start_of_local_day(d + timedelta(days=1), user)
                q &= Q(**{f"{field_name}__gte": next_day})
            else:
                q &= Q(**{f"{field_name}__gt": d})
        elif op == "gte":
            d = _resolve_date_token(arg, user)
            if is_datetime:
                q &= Q(**{f"{field_name}__gte": _start_of_local_day(d, user)})
            else:
                q &= Q(**{f"{field_name}__gte": d})
        elif op == "between":
            if not isinstance(arg, list) or len(arg) != 2:
                raise QueryEngineError(f"between must be [start, end] (got {arg!r})")
            start_d = _resolve_date_token(arg[0], user)
            end_d = _resolve_date_token(arg[1], user)
            if is_datetime:
                q &= Q(
                    **{
                        f"{field_name}__gte": _start_of_local_day(start_d, user),
                        f"{field_name}__lt": _start_of_local_day(
                            end_d + timedelta(days=1), user
                        ),
                    }
                )
            else:
                q &= Q(
                    **{
                        f"{field_name}__gte": start_d,
                        f"{field_name}__lte": end_d,
                    }
                )
        else:
            raise QueryEngineError(f"Unsupported op {op!r} on {field_name}")
    return q


def _date_eq_q(field_name: str, d: date, user, is_datetime: bool) -> Q:
    if is_datetime:
        start = _start_of_local_day(d, user)
        end = _start_of_local_day(d + timedelta(days=1), user)
        return Q(**{f"{field_name}__gte": start, f"{field_name}__lt": end})
    return Q(**{field_name: d})


def _scheduled_for_q(value: Any, user) -> Q:
    return _date_field_q("scheduled_for", value, user, is_datetime=False)


def _completed_at_q(value: Any, user) -> Q:
    return _date_field_q("completed_at", value, user, is_datetime=True)


def _has_tag_q(value: Any, user) -> Q:
    """Compose-friendly tag predicate.

    Each ``has_tag`` expands to an independent ``Exists()`` subquery
    against the Block.pages through table. That gives correct semantics
    under arbitrary combinator nesting — multiple ``has_tag`` under
    ``all`` AND together (each block must carry every named tag), under
    ``any`` they OR together, and the same predicate composes inside a
    nested tree without the join-reuse trap.
    """
    if isinstance(value, dict):
        value = value.get("eq")
    if not isinstance(value, str) or not value.strip():
        raise QueryEngineError(f"has_tag must be a slug string: {value!r}")

    slug = value.strip().lower()
    through = Block.pages.through
    sub = through.objects.filter(
        block_id=OuterRef("pk"),
        page__slug=slug,
        page__user=user,
    )
    return Q(Exists(sub))


def _has_property_q(value: Any, user) -> Q:
    if isinstance(value, dict):
        value = value.get("eq")
    if not isinstance(value, str) or not value:
        raise QueryEngineError(f"has_property must be a key string: {value!r}")
    return Q(properties__has_key=value)


def _property_eq_q(value: Any, user) -> Q:
    """Exact-match predicate against ``Block.properties[key]``.

    Property values are stringly-typed today (the inline ``key:: value``
    parser stores ``value.strip()`` as a string) — so this matches a
    string-vs-string. Numeric / typed comparisons are out of scope until
    typed properties land.
    """
    if not isinstance(value, dict):
        raise QueryEngineError(f"property_eq must be {{key, value}}: {value!r}")
    key = value.get("key")
    val = value.get("value")
    if not isinstance(key, str) or not key:
        raise QueryEngineError(f"property_eq.key must be a string: {key!r}")
    if val is None:
        raise QueryEngineError("property_eq.value is required")
    return Q(**{f"properties__{key}": val})


def _content_contains_q(value: Any, user) -> Q:
    if isinstance(value, dict):
        value = value.get("eq")
    if not isinstance(value, str) or not value:
        raise QueryEngineError(
            f"content_contains must be a non-empty string: {value!r}"
        )
    return Q(content__icontains=value)


PREDICATE_HANDLERS: Dict[str, Callable[[Any, Any], Q]] = {
    "block_type": _block_type_q,
    "scheduled_for": _scheduled_for_q,
    "completed_at": _completed_at_q,
    "has_tag": _has_tag_q,
    "has_property": _has_property_q,
    "property_eq": _property_eq_q,
    "content_contains": _content_contains_q,
}

COMBINATORS = ("all", "any")


# ---------------------------------------------------------------------------
# Top-level compile
# ---------------------------------------------------------------------------


def _compile_node(spec: Any, user) -> Q:
    if not isinstance(spec, dict):
        raise QueryEngineError(
            f"Filter node must be a dict, got {type(spec).__name__}: {spec!r}"
        )
    if not spec:
        return Q()  # vacuous true — matches all
    if len(spec) != 1:
        raise QueryEngineError(
            "Filter node must have exactly one key (field or combinator), "
            f"got {sorted(spec.keys())!r}"
        )

    key, value = next(iter(spec.items()))

    if key in COMBINATORS:
        if not isinstance(value, list) or not value:
            raise QueryEngineError(
                f"{key!r} combinator requires a non-empty list of children"
            )
        children = [_compile_node(child, user) for child in value]
        if key == "all":
            combined = Q()
            for child_q in children:
                combined &= child_q
            return combined
        # any
        combined = children[0]
        for child_q in children[1:]:
            combined |= child_q
        return combined

    handler = PREDICATE_HANDLERS.get(key)
    if handler is None:
        raise QueryEngineError(f"Unknown filter field/combinator: {key!r}")
    return handler(value, user)


_SORT_FIELDS = {
    "scheduled_for",
    "completed_at",
    "created_at",
    "modified_at",
    "order",
    "block_type",
}


def _compile_sort(sort_spec: Any) -> List[str]:
    if not sort_spec:
        return []
    if not isinstance(sort_spec, list):
        raise QueryEngineError("Sort must be a list of {field, dir} dicts")

    parts: List[str] = []
    for item in sort_spec:
        if not isinstance(item, dict) or "field" not in item:
            raise QueryEngineError(f"Sort item must be {{field, dir}}: {item!r}")
        f = item["field"]
        if f not in _SORT_FIELDS:
            raise QueryEngineError(f"Unsupported sort field: {f!r}")
        direction = item.get("dir", "asc")
        if direction not in ("asc", "desc"):
            raise QueryEngineError(f"Sort dir must be 'asc' or 'desc': {direction!r}")
        parts.append(f"-{f}" if direction == "desc" else f)
    return parts


def compile(spec: Any, user, sort: Any = None) -> CompiledQuery:
    """Compile a filter spec (and optional sort spec) into a CompiledQuery.

    Resolution of relative date tokens happens here against
    ``user.today()`` — meaning "today" snaps at compile time, not at
    queryset evaluation, so a freshly-compiled query is always evaluated
    against a stable today.
    """
    return CompiledQuery(
        filter_q=_compile_node(spec, user),
        order_by=_compile_sort(sort),
    )
