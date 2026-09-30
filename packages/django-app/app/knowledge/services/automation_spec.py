"""Parse a ``#automation`` block into a validated ``AutomationSpec``.

Automations are authored in the graph (issue #143): a block tagged
``#automation`` whose ``key:: value`` props configure it, e.g.

    Morning sticky sweep #automation
    trigger:: schedule daily 6:00
    query:: view:sticky-todos
    action:: move_to_daily today
    allow:: move_to_daily
    enabled:: true

The props land in ``block.properties`` (Block.extract_properties_from_content
syncs them from content). This module turns that stringly-typed dict into a
structured, validated spec. It does no DB I/O — callers resolve the
``query`` view slug and dispatch the ``action`` elsewhere.

Recognized props (slice 1 — schedule + manual triggers, command actions):

- ``trigger::`` ``schedule <cadence>`` | ``manual``
  cadence: ``daily HH:MM`` | ``hourly`` | ``weekly <dow> HH:MM`` |
  ``every <N>m|<N>h`` | ``cron <expr>`` (raw escape hatch)
- ``query::``   ``view:<saved-view-slug>`` (optional for ``manual``; the
  action decides whether it needs a result set)
- ``action::``  ``<verb> <args...> [then <verb> <args...>]…`` (issue #225)
  — one or more steps run in order, sharing the same matched-block set;
  verbs are validated by the action registry, not here
- ``allow::``   comma/space separated capability list (tool/verb names the
  run may execute without interactive approval). OPTIONAL for command
  actions: omitted means "exactly the declared verb" — the action line
  itself is the authorization. It stays load-bearing (and will be
  required) for the ``prompt`` action, where it bounds which write tools
  the LLM may use.
- ``enabled::`` ``true`` (default) | ``false``
- ``for::``     ``<n>,<n>,...`` | ``<n>..<m> by <k>`` (issue #209) — a
  literal iteration source for a standalone action, binding ``{{item}}``.
  Integers, ascending, max ``MAX_FOR_ITEMS``. Mutually exclusive with
  ``query::`` — an automation has exactly one iteration source (the
  query's matched blocks, or ``for::``'s literal items), never both.

Action args may carry ``{{token}}`` placeholders (issue #209), resolved
by ``services.content_tokens`` / ``services.automation_actions`` at run
time — this module only enforces the two token/spec contracts that don't
need the verb registry: ``{{block.*}}`` tokens require ``query::``, and
``for::``/``query::`` can't both be set. Everything else about tokens
(unknown names, ``{{item}}`` used outside ``for::``, which verbs accept
``{{block.*}}``) is a run-time ``ActionError``, not a parse error.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Tuple

from django.utils.text import slugify

from .content_tokens import token_names
from .query_dsl import QueryDSLError, compile_inline_query

if TYPE_CHECKING:
    from knowledge.models import Block

# Slug of the tag that marks a block as an automation definition.
AUTOMATION_TAG_SLUG = "automation"

_AUTOMATION_HASHTAG_RE = re.compile(r"(?<!\\)#automation\b")


def is_automation_content(content: str, page_slug: str) -> bool:
    """True when ``content`` on a page slugged ``page_slug`` would enroll
    as an ``#automation`` definition block — mirrors
    ``BlockRepository._automation_blocks_qs``'s discovery predicate (the
    ``#automation`` hashtag, or living on the seeded "Automations" page).

    Content-token resolution (issue #140) skips these blocks: a `key::
    value` line like ``action:: create_block "{{item}}" ...`` carries the
    automation token vocabulary (issue #209), which
    ``automation_actions.run_action`` resolves at run time — often
    against a context (a matched block, a `for::` item) that doesn't
    exist yet at save time. Eagerly resolving it there raised on every
    save of an automation using ``{{item}}``/``{{block.*}}``, and would
    silently freeze ``{{today}}``/``{{now}}`` to authoring time instead
    of each run's own."""
    if page_slug == AUTOMATION_TAG_SLUG:
        return True
    return bool(_AUTOMATION_HASHTAG_RE.search(content or ""))


TRIGGER_SCHEDULE = "schedule"
TRIGGER_MANUAL = "manual"

SCHEDULE_DAILY = "daily"
SCHEDULE_HOURLY = "hourly"
SCHEDULE_WEEKLY = "weekly"
SCHEDULE_EVERY = "every"
SCHEDULE_CRON = "cron"

_EVERY_RE = re.compile(r"^(\d+)([mh])$")

# Monday-first, matching Python's date.weekday().
_WEEKDAYS = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class AutomationSpecError(ValueError):
    """A ``#automation`` block could not be parsed into a valid spec.

    Carries the list of human-readable problems so the caller can surface
    them on the block / record them on a failed AutomationRun rather than
    failing opaquely."""

    def __init__(self, errors: List[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class ScheduleSpec:
    """A normalized schedule cadence. ``kind`` selects which fields apply.

    Due-ness is computed by the scheduler (run_due_automations), not here —
    this is purely the parsed shape."""

    raw: str
    kind: str  # daily | hourly | weekly | every | cron (SCHEDULE_* constants)
    hour: Optional[int] = None
    minute: Optional[int] = None
    weekday: Optional[int] = None  # 0 = Monday
    interval_minutes: Optional[int] = None  # SCHEDULE_EVERY only
    cron: Optional[str] = None


@dataclass(frozen=True)
class TriggerSpec:
    kind: str  # TRIGGER_SCHEDULE | TRIGGER_MANUAL
    schedule: Optional[ScheduleSpec] = None


QUERY_VIEW = "view"
QUERY_INLINE = "inline"


@dataclass(frozen=True)
class QuerySpec:
    kind: str  # QUERY_VIEW | QUERY_INLINE
    view_slug: str = ""
    # Compiled query-engine filter dict — QUERY_INLINE only.
    filter_spec: Optional[dict] = None


@dataclass(frozen=True)
class ActionSpec:
    verb: str
    args: Tuple[str, ...]
    raw: str


@dataclass(frozen=True)
class ActionChainSpec:
    """One or more ``ActionSpec`` steps, separated by a bare ``then`` on
    the ``action::`` line (issue #225). A line with no ``then`` compiles
    to a one-step chain, so ``.raw`` is always the whole ``action::``
    line — existing single-verb consumers (``list_automations_command``)
    that read ``action.raw`` keep working unchanged."""

    steps: Tuple[ActionSpec, ...]
    raw: str


# Cap on `for::`'s item count — a typo'd range (`for:: 1..100000 by 1`)
# can't fan a standalone action out unbounded (mirrors MAX_ACTION_BLOCKS
# for the query side of iteration).
MAX_FOR_ITEMS = 50

_FOR_RANGE_RE = re.compile(r"^(\d+)\s*\.\.\s*(\d+)\s+by\s+(\d+)$")


@dataclass(frozen=True)
class ForSpec:
    """A ``for::`` iteration source (issue #209): a literal, ordered list
    of string items binding ``{{item}}`` — the standalone-action
    counterpart to a query's matched blocks."""

    items: Tuple[str, ...]
    raw: str


@dataclass(frozen=True)
class AutomationSpec:
    block_uuid: str
    name: str
    slug: str
    trigger: TriggerSpec
    action: ActionChainSpec
    # None = the `allow::` prop was omitted entirely; the runner then grants
    # every verb declared in the chain. An explicit (even empty) list is
    # honored as written.
    allow: Optional[frozenset]
    enabled: bool
    query: Optional[QuerySpec] = None
    for_spec: Optional[ForSpec] = None


def parse_automation_block(block: "Block") -> AutomationSpec:
    """Compile a ``#automation`` block into an ``AutomationSpec``.

    Raises ``AutomationSpecError`` (with every problem found, not just the
    first) when the block is malformed."""
    props = block.properties or {}
    errors: List[str] = []

    name = _derive_name(block)
    slug = slugify(name) or str(block.uuid)

    trigger = _parse_trigger(_prop_str(props, "trigger"), errors)
    query = _parse_query(_prop_str(props, "query"), errors)
    action = _parse_action(_prop_str(props, "action"), errors)
    for_spec = _parse_for(_prop_str(props, "for"), errors) if "for" in props else None
    allow = _parse_allow(_prop_str(props, "allow")) if "allow" in props else None
    enabled = _parse_bool(_prop_str(props, "enabled", "true"))

    if action is not None:
        arg_tokens = [
            name
            for step in action.steps
            for arg in step.args
            for name in token_names(arg)
        ]
        if any(name.startswith("block.") for name in arg_tokens) and query is None:
            errors.append(
                "action args use `{{block.*}}` tokens, which require a `query::`"
            )
        if "item" in arg_tokens and for_spec is None:
            errors.append("`{{item}}` requires a `for::` directive")
        if for_spec is not None and len(action.steps) > 1:
            errors.append(
                "`for::` doesn't support a multi-step action chain "
                "(`then`) — use a single verb"
            )

    if for_spec is not None and query is not None:
        errors.append(
            "`for::` and `query::` are mutually exclusive — an automation "
            "has one iteration source"
        )

    if errors:
        raise AutomationSpecError(errors)

    return AutomationSpec(
        block_uuid=str(block.uuid),
        name=name,
        slug=slug,
        trigger=trigger,  # type: ignore[arg-type]
        action=action,  # type: ignore[arg-type]
        allow=allow,
        enabled=enabled,
        query=query,
        for_spec=for_spec,
    )


def _prop_str(props: dict, key: str, default: str = "") -> str:
    """Read a property as a string. ``block.properties`` is a JSONField and
    ``set_property`` accepts any JSON value, so a programmatic writer can
    store a bool/int (``enabled:: true`` saved as ``True``). Coerce instead
    of crashing — ``str(True).lower()`` is ``"true"``, which is what the
    parsers expect anyway."""
    value = props.get(key, default)
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _derive_name(block: "Block") -> str:
    """The automation's display name: the block's first content line with
    the ``#automation`` tag and any inline props stripped."""
    text = block.first_content_line()
    # Drop the #automation hashtag and any trailing inline `key:: value`.
    text = re.sub(r"#\w[\w-]*", "", text)
    text = re.sub(r"\b[a-zA-Z0-9_-]+::.*$", "", text)
    cleaned = text.strip()
    return cleaned or "Automation"


def _parse_trigger(raw: str, errors: List[str]) -> Optional[TriggerSpec]:
    raw = (raw or "").strip()
    if not raw:
        errors.append("missing `trigger::`")
        return None

    parts = raw.split(maxsplit=1)
    kind = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    if kind == TRIGGER_MANUAL:
        return TriggerSpec(kind=TRIGGER_MANUAL)
    if kind == TRIGGER_SCHEDULE:
        schedule = _parse_schedule(rest, errors)
        return TriggerSpec(kind=TRIGGER_SCHEDULE, schedule=schedule)

    errors.append(
        f"unknown trigger `{kind}` (expected `schedule` or `manual` in this version)"
    )
    return None


def _parse_schedule(raw: str, errors: List[str]) -> Optional[ScheduleSpec]:
    raw = (raw or "").strip()
    if not raw:
        errors.append("`trigger:: schedule` needs a cadence (e.g. `daily 6:00`)")
        return None

    parts = raw.split()
    head = parts[0].lower()

    if head == SCHEDULE_HOURLY:
        return ScheduleSpec(raw=raw, kind=SCHEDULE_HOURLY, minute=0)

    if head == SCHEDULE_DAILY:
        hm = _parse_time(parts[1]) if len(parts) > 1 else (0, 0)
        if hm is None:
            errors.append(f"bad time in `daily {parts[1]}` (expected HH:MM)")
            return None
        return ScheduleSpec(raw=raw, kind=SCHEDULE_DAILY, hour=hm[0], minute=hm[1])

    if head == SCHEDULE_WEEKLY:
        if len(parts) < 2 or parts[1].lower() not in _WEEKDAYS:
            errors.append("`weekly` needs a weekday (e.g. `weekly mon 9:00`)")
            return None
        weekday = _WEEKDAYS[parts[1].lower()]
        hm = _parse_time(parts[2]) if len(parts) > 2 else (0, 0)
        if hm is None:
            errors.append(
                f"bad time in `weekly {parts[1]} {parts[2]}` (expected HH:MM)"
            )
            return None
        return ScheduleSpec(
            raw=raw,
            kind=SCHEDULE_WEEKLY,
            weekday=weekday,
            hour=hm[0],
            minute=hm[1],
        )

    if head == SCHEDULE_EVERY:
        token = parts[1].lower() if len(parts) > 1 else ""
        m = _EVERY_RE.match(token)
        if not m:
            errors.append("`every` expects an interval like `every 15m` or `every 2h`")
            return None
        amount, unit = int(m.group(1)), m.group(2)
        minutes = amount * 60 if unit == "h" else amount
        if minutes < 1:
            errors.append("`every` interval must be at least 1 minute")
            return None
        return ScheduleSpec(raw=raw, kind=SCHEDULE_EVERY, interval_minutes=minutes)

    if head == SCHEDULE_CRON:
        cron = raw.split(maxsplit=1)[1].strip() if len(parts) > 1 else ""
        if len(cron.split()) != 5:
            errors.append("`cron` expects a 5-field expression (m h dom mon dow)")
            return None
        return ScheduleSpec(raw=raw, kind=SCHEDULE_CRON, cron=cron)

    errors.append(
        f"unknown cadence `{head}` (expected daily / hourly / weekly / every / cron)"
    )
    return None


def _parse_time(token: str) -> Optional[Tuple[int, int]]:
    m = _TIME_RE.match(token.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _parse_query(raw: str, errors: List[str]) -> Optional[QuerySpec]:
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.startswith("view:"):
        slug = raw[len("view:") :].strip()
        if not slug:
            errors.append("`query:: view:` needs a saved-view slug")
            return None
        return QuerySpec(kind=QUERY_VIEW, view_slug=slug)
    try:
        filter_spec = compile_inline_query(raw)
    except QueryDSLError as exc:
        errors.append(f"bad query: {exc}")
        return None
    return QuerySpec(kind=QUERY_INLINE, filter_spec=filter_spec)


def _parse_for(raw: str, errors: List[str]) -> Optional[ForSpec]:
    raw = (raw or "").strip()
    if not raw:
        errors.append("`for::` needs items, e.g. `for:: 5,10,15` or `for:: 5..30 by 5`")
        return None

    match = _FOR_RANGE_RE.match(raw)
    if match:
        start, end, step = (int(match.group(i)) for i in (1, 2, 3))
        if step < 1:
            errors.append("`for::` range step (`by`) must be at least 1")
            return None
        if start > end:
            errors.append("`for::` range must be ascending (start <= end)")
            return None
        items = [str(n) for n in range(start, end + 1, step)]
    else:
        parts = [p.strip() for p in raw.split(",")]
        if any(not p for p in parts):
            errors.append("`for::` has an empty item in the comma-separated list")
            return None
        try:
            values = [int(p) for p in parts]
        except ValueError:
            errors.append(
                "`for::` items must be integers — a comma list (`5,10,15`) "
                "or a range (`5..30 by 5`)"
            )
            return None
        if values != sorted(values) or len(set(values)) != len(values):
            errors.append("`for::` items must be strictly ascending")
            return None
        items = parts

    if len(items) > MAX_FOR_ITEMS:
        errors.append(
            f"`for::` produces {len(items)} items, over the {MAX_FOR_ITEMS} cap"
        )
        return None
    return ForSpec(items=tuple(items), raw=raw)


def _parse_action(raw: str, errors: List[str]) -> Optional[ActionChainSpec]:
    raw = (raw or "").strip()
    if not raw:
        errors.append("missing `action::`")
        return None

    segments = _split_chain_segments(raw, errors)
    if segments is None:
        return None
    if any(not segment.strip() for segment in segments):
        errors.append(
            "`action::` has an empty step around `then` — expected "
            "`<verb> [args] then <verb> [args]`"
        )
        return None

    steps: List[ActionSpec] = []
    for segment in segments:
        segment = segment.strip()
        parts = segment.split(maxsplit=1)
        verb = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""
        args = _split_args(rest, errors)
        steps.append(ActionSpec(verb=verb, args=tuple(args), raw=segment))

    return ActionChainSpec(steps=tuple(steps), raw=raw)


def _split_chain_segments(raw: str, errors: List[str]) -> Optional[List[str]]:
    """Tokenize ``raw`` with quotes preserved and split on bare ``then``
    tokens, so a quoted ``"...then..."`` never breaks a chain in two.
    Splitting can't happen after ``shlex.split`` (posix mode), which
    strips quotes and makes a quoted ``"then"`` indistinguishable from a
    bare one."""
    try:
        lexer = shlex.shlex(raw, posix=False)
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        errors.append(f"unbalanced quotes in action args: `{raw}`")
        return None

    segments: List[List[str]] = [[]]
    for token in tokens:
        if token == "then":
            segments.append([])
        else:
            segments[-1].append(token)
    return [" ".join(segment) for segment in segments]


def _split_args(rest: str, errors: List[str]) -> List[str]:
    """Split action args shell-style, so quoted spans stay single args in
    any position: ``notify "still on this?" today`` → two args, quotes
    stripped. Unbalanced quotes are a spec error, not a crash."""
    if not rest:
        return []
    try:
        return shlex.split(rest)
    except ValueError:
        errors.append(f"unbalanced quotes in action args: `{rest}`")
        return []


def _parse_allow(raw: str) -> frozenset:
    raw = (raw or "").strip()
    if not raw:
        return frozenset()
    tokens = [t.strip() for t in re.split(r"[,\s]+", raw) if t.strip()]
    return frozenset(tokens)


def _parse_bool(raw: str) -> bool:
    return (raw or "").strip().lower() not in {"false", "no", "0", "off"}
