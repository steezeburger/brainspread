"""Structured filter → Django Q compiler for SavedView (issue #60).

The filter spec is JSON with two flavors of node:

- **Combinator**: ``{"all": [<node>, ...]}`` or ``{"any": [<node>, ...]}``
  combines child nodes under AND / OR. ``{"not": <node>}`` negates a
  single child (``"Glitch's favorites without Jesse"`` =
  ``all: [has_tag glitch, has_tag favorite-things, not: {has_tag jesse}]``).
- **Predicate**: ``{<field>: <value-or-op-dict>}`` where ``<field>`` is one
  of the supported predicate names. ``<value>`` is either a scalar
  shorthand (interpreted as ``eq``) or a dict of ``{op: arg, ...}``.

Supported predicates and their ops are listed in :data:`PREDICATE_HANDLERS`.
Date tokens (``today``, ``tomorrow``, ``yesterday``, ``N days ago``,
``N days from now``, ISO ``YYYY-MM-DD``) are resolved at execute time
against ``user.today()`` so views stay relative.

``key:: value`` block properties are queryable through ``has_property``
(key existence) and ``property_eq`` (op-dict against the value). Values
are stringly-typed today — the inline parser stores ``value.strip()`` —
so all comparisons are string-vs-string. Sort by a JSONB key with
``{"field": "properties.<key>", "dir": ...}``.

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
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List

from django.db.models import Exists, OuterRef, Q

from knowledge.models import Block
from knowledge.services.due_dates import start_of_local_day

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
    # When False (the default), the repository excludes blocks whose page
    # is a template — they're scaffolding, not active work, and surfacing
    # them in "Overdue" / tag views is almost always noise. Set to True
    # when the filter explicitly mentions ``page_type`` so a power user
    # can opt template blocks back in (e.g. ``{"page_type": "template"}``).
    includes_page_type: bool = False


# ---------------------------------------------------------------------------
# Date token resolution
# ---------------------------------------------------------------------------

_DAYS_AGO_RE = re.compile(r"^(\d+)\s+days?\s+ago$")
_DAYS_FROM_NOW_RE = re.compile(r"^(?:in\s+(\d+)\s+days?|(\d+)\s+days?\s+from\s+now)$")


def _resolve_date_token(raw: Any, user, context_date: "date | None" = None) -> date:
    """Turn a token (``"today"``, ``"3 days ago"``, ``"2026-05-01"``, or a
    ``date``/``datetime``) into a concrete date in the user's timezone.

    When ``context_date`` is provided it's used as the anchor for relative
    tokens (``today`` / ``yesterday`` / ``N days ago`` / ``N days from
    now``) instead of ``user.today()``. The "Dates relative to daily"
    flag on SavedView drives this — embedded views on a daily page pass
    that daily's date so date filters rebase to the page in view.
    ISO date strings ignore ``context_date`` (they're absolute by
    construction)."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str):
        raise QueryEngineError(
            f"Expected date string, got {type(raw).__name__}: {raw!r}"
        )

    s = raw.strip().lower()
    today = context_date if context_date is not None else user.today()

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
    """Aware datetime at midnight of d in the user's timezone. Thin adapter
    over the shared implementation in services.due_dates so day-boundary
    semantics can't drift from the repository's."""
    return start_of_local_day(d, user.tz())


# ---------------------------------------------------------------------------
# Predicate handlers
# ---------------------------------------------------------------------------

# Pulled from Block.block_type choices; refresh if the model gains new types.
_BLOCK_TYPES = {choice[0] for choice in Block._meta.get_field("block_type").choices}


def _block_type_q(value: Any, user, context_date: "date | None" = None) -> Q:
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


def _date_field_q(
    field_name: str,
    value: Any,
    user,
    is_datetime: bool,
    context_date: "date | None" = None,
) -> Q:
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
            d = _resolve_date_token(arg, user, context_date)
            q &= _date_eq_q(field_name, d, user, is_datetime)
        elif op == "lt":
            d = _resolve_date_token(arg, user, context_date)
            if is_datetime:
                q &= Q(**{f"{field_name}__lt": _start_of_local_day(d, user)})
            else:
                q &= Q(**{f"{field_name}__lt": d})
        elif op == "lte":
            d = _resolve_date_token(arg, user, context_date)
            if is_datetime:
                next_day = _start_of_local_day(d + timedelta(days=1), user)
                q &= Q(**{f"{field_name}__lt": next_day})
            else:
                q &= Q(**{f"{field_name}__lte": d})
        elif op == "gt":
            d = _resolve_date_token(arg, user, context_date)
            if is_datetime:
                next_day = _start_of_local_day(d + timedelta(days=1), user)
                q &= Q(**{f"{field_name}__gte": next_day})
            else:
                q &= Q(**{f"{field_name}__gt": d})
        elif op == "gte":
            d = _resolve_date_token(arg, user, context_date)
            if is_datetime:
                q &= Q(**{f"{field_name}__gte": _start_of_local_day(d, user)})
            else:
                q &= Q(**{f"{field_name}__gte": d})
        elif op == "between":
            if not isinstance(arg, list) or len(arg) != 2:
                raise QueryEngineError(f"between must be [start, end] (got {arg!r})")
            start_d = _resolve_date_token(arg[0], user, context_date)
            end_d = _resolve_date_token(arg[1], user, context_date)
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


def _due_at_q(value: Any, user, context_date: "date | None" = None) -> Q:
    return _date_field_q(
        "due_at", value, user, is_datetime=True, context_date=context_date
    )


def _completed_at_q(value: Any, user, context_date: "date | None" = None) -> Q:
    return _date_field_q(
        "completed_at", value, user, is_datetime=True, context_date=context_date
    )


def _has_tag_q(value: Any, user, context_date: "date | None" = None) -> Q:
    """Compose-friendly tag predicate.

    Matches a block when *either*:

      • the block lives on a page with the given slug
        (``block.page.slug == X``), or
      • the block has an explicit hashtag/wiki-link reference to a
        page with that slug (the ``Block.pages`` M2M).

    The user-facing model treats "this block is on page X" and "this
    block has #X" as the same organizational signal — a block written
    under page foo is implicitly about foo, even if the user didn't
    type #foo on the line itself. Surfaces that ask "is this block
    about X?" (this predicate, the tag-content view) honor that;
    surfaces that ask "does this block reference X from elsewhere?"
    (backlinks) intentionally do not, since a child block on page X
    isn't a cross-reference to X.

    Each ``has_tag`` expands to an independent expression so multi-
    has_tag composes correctly under any combinator nesting — the
    M2M side uses an ``Exists()`` subquery so AND across distinct
    tags doesn't collapse via join reuse.
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
    page_membership = Q(page__slug=slug, page__user=user)
    return page_membership | Q(Exists(sub))


# Property keys are constrained to the same charset the parser accepts in
# ``Block.extract_properties_from_content`` (``[a-zA-Z0-9_-]+``). Once we're
# inside ``properties__<key>`` Django interprets further ``__`` segments as
# nested JSON-path lookups, not as model traversals, so the validation is
# mainly a hygiene check — keep query keys to the same shape the inline
# parser produces, since those are the only keys real blocks will have.
_PROPERTY_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

_PROPERTY_OPS = {
    "eq",
    "ne",
    "in",
    "not_in",
    "contains",
    "starts_with",
    "ends_with",
    "lt",
    "lte",
    "gt",
    "gte",
}


def _validate_property_key(key: Any, predicate: str) -> str:
    if not isinstance(key, str) or not key:
        raise QueryEngineError(f"{predicate}.key must be a string: {key!r}")
    if not _PROPERTY_KEY_RE.match(key):
        raise QueryEngineError(f"{predicate}.key must match [a-zA-Z0-9_-]+: {key!r}")
    return key


def _has_property_q(value: Any, user, context_date: "date | None" = None) -> Q:
    if isinstance(value, dict):
        value = value.get("eq")
    key = _validate_property_key(value, "has_property")
    return Q(properties__has_key=key)


def _property_eq_q(value: Any, user, context_date: "date | None" = None) -> Q:
    """Op-dict predicate against ``Block.properties[key]``.

    Shorthand ``{"key": K, "value": V}`` is treated as ``{"key": K,
    "eq": V}`` for backwards compatibility with the original ``eq``-only
    shape. The general form is ``{"key": K, <op>: <arg>, ...}`` where
    multiple ops AND together (e.g. ``{"gte": "2h", "lte": "5h"}``).

    Property values are stringly-typed today — the inline ``key:: value``
    parser stores ``value.strip()`` as a string — so all comparisons are
    string-vs-string. That's intentionally good enough for ISO date
    strings (``due:: 2026-05-01`` compares lexicographically the way
    you'd want) and dollar-prefixed money (``cost:: $042``), but it
    does mean ``estimate:: 10`` sorts before ``estimate:: 2``. Numeric
    coercion lands when typed properties do.

    ``ne`` / ``not_in`` match blocks that have the key set to something
    other than the given value(s); blocks that don't have the key at
    all are *not* matched (SQL ``NULL <> 'x'`` is NULL). Use
    ``{"any": [{"property_eq": {...ne...}}, {"not": {"has_property":
    "K"}}]}`` if you also want missing-key blocks.
    """
    if not isinstance(value, dict):
        raise QueryEngineError(f"property_eq must be a dict: {value!r}")
    key = _validate_property_key(value.get("key"), "property_eq")

    ops = {k: v for k, v in value.items() if k != "key"}
    if "value" in ops:
        # Legacy shorthand: {"key": K, "value": V} == {"key": K, "eq": V}.
        # Reject collision with an explicit eq so the spec stays unambiguous.
        if "eq" in ops:
            raise QueryEngineError("property_eq cannot specify both 'value' and 'eq'")
        ops["eq"] = ops.pop("value")

    if not ops:
        raise QueryEngineError(
            "property_eq requires at least one op (eq/ne/in/not_in/"
            "contains/starts_with/ends_with/lt/lte/gt/gte) or 'value'"
        )

    lookup = f"properties__{key}"
    q = Q()
    for op, arg in ops.items():
        if op not in _PROPERTY_OPS:
            raise QueryEngineError(f"Unsupported op {op!r} on property_eq")
        if op == "eq":
            if arg is None:
                raise QueryEngineError("property_eq.eq must not be null")
            q &= Q(**{lookup: arg})
        elif op == "ne":
            if arg is None:
                raise QueryEngineError("property_eq.ne must not be null")
            q &= ~Q(**{lookup: arg})
        elif op == "in":
            if not isinstance(arg, list) or not arg:
                raise QueryEngineError(
                    f"property_eq.in must be a non-empty list: {arg!r}"
                )
            q &= Q(**{f"{lookup}__in": arg})
        elif op == "not_in":
            if not isinstance(arg, list) or not arg:
                raise QueryEngineError(
                    f"property_eq.not_in must be a non-empty list: {arg!r}"
                )
            q &= ~Q(**{f"{lookup}__in": arg})
        elif op == "contains":
            if not isinstance(arg, str) or not arg:
                raise QueryEngineError(
                    f"property_eq.contains must be a non-empty string: {arg!r}"
                )
            q &= Q(**{f"{lookup}__icontains": arg})
        elif op == "starts_with":
            if not isinstance(arg, str) or not arg:
                raise QueryEngineError(
                    f"property_eq.starts_with must be a non-empty string: {arg!r}"
                )
            q &= Q(**{f"{lookup}__istartswith": arg})
        elif op == "ends_with":
            if not isinstance(arg, str) or not arg:
                raise QueryEngineError(
                    f"property_eq.ends_with must be a non-empty string: {arg!r}"
                )
            q &= Q(**{f"{lookup}__iendswith": arg})
        else:  # lt / lte / gt / gte
            if not isinstance(arg, (str, int, float)):
                raise QueryEngineError(f"property_eq.{op} must be a scalar: {arg!r}")
            q &= Q(**{f"{lookup}__{op}": arg})
    return q


def _content_contains_q(value: Any, user, context_date: "date | None" = None) -> Q:
    if isinstance(value, dict):
        value = value.get("eq")
    if not isinstance(value, str) or not value:
        raise QueryEngineError(
            f"content_contains must be a non-empty string: {value!r}"
        )
    return Q(content__icontains=value)


# Pulled from Page.page_type choices; refresh if the model gains new types.
# Resolved lazily to avoid an import cycle at module load.
def _page_types() -> "set[str]":
    from knowledge.models import Page

    return {choice[0] for choice in Page._meta.get_field("page_type").choices}


def _page_type_q(value: Any, user, context_date: "date | None" = None) -> Q:
    """Filter blocks by their page's ``page_type``.

    Shorthand ``"template"`` is treated as ``{"eq": "template"}``. The
    main reason this predicate exists is to let users opt template-page
    blocks back into a view's results — by default the repository
    excludes them as scaffolding (see CompiledQuery.includes_page_type).
    Mentioning ``page_type`` anywhere in the filter (including a
    negation) turns the default exclusion off so the spec stays in
    control.
    """
    if isinstance(value, str):
        value = {"eq": value}
    if not isinstance(value, dict):
        raise QueryEngineError(f"Invalid page_type predicate: {value!r}")

    page_types = _page_types()
    q = Q()
    for op, arg in value.items():
        if op == "eq":
            if arg not in page_types:
                raise QueryEngineError(f"Unknown page_type: {arg!r}")
            q &= Q(page__page_type=arg)
        elif op == "in":
            if not isinstance(arg, list) or not arg:
                raise QueryEngineError(
                    f"page_type 'in' must be a non-empty list: {arg!r}"
                )
            unknown = [v for v in arg if v not in page_types]
            if unknown:
                raise QueryEngineError(f"Unknown page_type(s): {unknown!r}")
            q &= Q(page__page_type__in=arg)
        else:
            raise QueryEngineError(f"Unsupported op {op!r} on page_type")
    return q


PREDICATE_HANDLERS: Dict[str, Callable[..., Q]] = {
    "block_type": _block_type_q,
    "due_at": _due_at_q,
    # Back-compat: filters authored before the scheduled_for→due_at rename
    # still compile against the renamed field.
    "scheduled_for": _due_at_q,
    "completed_at": _completed_at_q,
    "has_tag": _has_tag_q,
    "has_property": _has_property_q,
    "property_eq": _property_eq_q,
    "content_contains": _content_contains_q,
    "page_type": _page_type_q,
}

COMBINATORS = ("all", "any", "not")


# ---------------------------------------------------------------------------
# Top-level compile
# ---------------------------------------------------------------------------


def _compile_node(spec: Any, user, context_date: "date | None" = None) -> Q:
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
        if key == "not":
            # ``not`` takes a single child node, not a list. Lifting the
            # value into [value] would let users write ``{"not": []}``
            # which has no useful semantics (negation of "vacuous true"
            # matches nothing) and obscures typos like ``{"not": [a, b]}``
            # where they probably meant ``{"not": {"any": [a, b]}}``.
            if not isinstance(value, dict) or not value:
                raise QueryEngineError(
                    "'not' combinator requires a single non-empty filter "
                    "node as its value"
                )
            return ~_compile_node(value, user, context_date)

        if not isinstance(value, list) or not value:
            raise QueryEngineError(
                f"{key!r} combinator requires a non-empty list of children"
            )
        children = [_compile_node(child, user, context_date) for child in value]
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
    return handler(value, user, context_date)


_SORT_FIELDS = {
    "due_at",
    "completed_at",
    "created_at",
    "modified_at",
    "order",
    "block_type",
}

# Back-compat: legacy sorts referencing the pre-rename field name resolve to
# the renamed model field.
_SORT_FIELD_ALIASES = {"scheduled_for": "due_at"}


def _resolve_sort_field(raw: Any) -> str:
    """Validate a sort field and return the Django ORM expression for it.

    Accepts:
      - any name in ``_SORT_FIELDS`` (real model field)
      - ``properties.<key>`` to sort by a JSONB key. ``<key>`` must
        match the same charset the property parser accepts so we
        can safely interpolate it into the ORM lookup. Blocks that
        don't have ``<key>`` set sort as NULL (Postgres default:
        last in ASC, first in DESC).
    """
    if not isinstance(raw, str) or not raw:
        raise QueryEngineError(f"Sort field must be a non-empty string: {raw!r}")
    raw = _SORT_FIELD_ALIASES.get(raw, raw)
    if raw in _SORT_FIELDS:
        return raw
    if raw.startswith("properties."):
        key = raw.split(".", 1)[1]
        _validate_property_key(key, "sort.properties")
        return f"properties__{key}"
    raise QueryEngineError(f"Unsupported sort field: {raw!r}")


def _compile_sort(sort_spec: Any) -> List[str]:
    if not sort_spec:
        return []
    if not isinstance(sort_spec, list):
        raise QueryEngineError("Sort must be a list of {field, dir} dicts")

    parts: List[str] = []
    for item in sort_spec:
        if not isinstance(item, dict) or "field" not in item:
            raise QueryEngineError(f"Sort item must be {{field, dir}}: {item!r}")
        resolved = _resolve_sort_field(item["field"])
        direction = item.get("dir", "asc")
        if direction not in ("asc", "desc"):
            raise QueryEngineError(f"Sort dir must be 'asc' or 'desc': {direction!r}")
        parts.append(f"-{resolved}" if direction == "desc" else resolved)
    return parts


def _spec_mentions_page_type(spec: Any) -> bool:
    """True iff the filter spec references the ``page_type`` predicate.

    Used by ``compile`` to flip ``CompiledQuery.includes_page_type``,
    which in turn tells the repository to skip its default template-
    page exclusion. Walks through combinators (``all`` / ``any`` /
    ``not``) so a nested ``page_type`` still counts.
    """
    if not isinstance(spec, dict) or not spec:
        return False
    key, value = next(iter(spec.items()))
    if key == "page_type":
        return True
    if key == "not":
        return _spec_mentions_page_type(value)
    if key in ("all", "any") and isinstance(value, list):
        return any(_spec_mentions_page_type(child) for child in value)
    return False


def compile(
    spec: Any,
    user,
    sort: Any = None,
    context_date: "date | None" = None,
) -> CompiledQuery:
    """Compile a filter spec (and optional sort spec) into a CompiledQuery.

    Resolution of relative date tokens happens here against
    ``user.today()`` (or ``context_date`` if provided) — meaning "today"
    snaps at compile time, not at queryset evaluation, so a freshly-
    compiled query is always evaluated against a stable today.

    ``context_date`` is the "Dates relative to daily" plumbing: when a
    saved view is rendered as an embed on a daily page, the caller (the
    Run command) passes that daily's date so date tokens rebase to the
    page in view instead of the live current date. Pass ``None`` (the
    default) to keep the live-today semantics.
    """
    return CompiledQuery(
        filter_q=_compile_node(spec, user, context_date),
        order_by=_compile_sort(sort),
        includes_page_type=_spec_mentions_page_type(spec),
    )
