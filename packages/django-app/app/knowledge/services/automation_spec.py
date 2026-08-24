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
- ``action::``  ``<verb> <args...>`` — verbs are validated by the action
  registry, not here
- ``allow::``   comma/space separated capability list (tool/verb names the
  run may execute without interactive approval). OPTIONAL for command
  actions: omitted means "exactly the declared verb" — the action line
  itself is the authorization. It stays load-bearing (and will be
  required) for the ``prompt`` action, where it bounds which write tools
  the LLM may use.
- ``enabled::`` ``true`` (default) | ``false``
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Tuple

from django.utils.text import slugify

from ..constants import AUTOMATION_TAG_SLUG  # noqa: F401  (re-exported)
from .query_dsl import QueryDSLError, compile_inline_query

if TYPE_CHECKING:
    from knowledge.models import Block

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
class AutomationSpec:
    block_uuid: str
    name: str
    slug: str
    trigger: TriggerSpec
    action: ActionSpec
    # None = the `allow::` prop was omitted entirely; the runner then grants
    # exactly the declared verb. An explicit (even empty) list is honored
    # as written.
    allow: Optional[frozenset]
    enabled: bool
    query: Optional[QuerySpec] = None


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
    allow = _parse_allow(_prop_str(props, "allow")) if "allow" in props else None
    enabled = _parse_bool(_prop_str(props, "enabled", "true"))

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


def _parse_action(raw: str, errors: List[str]) -> Optional[ActionSpec]:
    raw = (raw or "").strip()
    if not raw:
        errors.append("missing `action::`")
        return None
    parts = raw.split(maxsplit=1)
    verb = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""
    args = _split_args(rest, errors)
    return ActionSpec(verb=verb, args=tuple(args), raw=raw)


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
