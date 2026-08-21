"""Content token resolver (issue #140).

``{{token}}`` placeholders in block content, resolved once at a binding
point and frozen — **snapshot-only**: there are no live/re-evaluating
tokens, and a resolved value never changes afterwards (decided on the
issue). The two v1 binding points are block save (CreateBlockCommand /
UpdateBlockCommand) and template apply (AddTemplateBlocksToPageCommand);
automation action args (issue #209) will consume the same module.
Templates are blueprints: tokens stay dormant in ``page_type=template``
content and resolve only when the template is applied — the consumers
enforce that by simply not calling the resolver for template pages.

Snapshot freezing is a feature, not a limitation: a frozen
``{{count:<query>}}`` inside a recurring template becomes a time series
across dailies — e.g. a weekly review template containing
``Open going into the week: {{count:type:todo and completed is null}}``
records that week's number forever, one frozen sample per apply.

Grammar::

    token   := "{{" base ("|" filter)* "}}"
    base    := name (":" arg)?          # arg only on input / count
    filter  := fname (":" farg)?        # farg is raw text after the colon

Filters are pipe-chained, Jinja-style (the syntax decision on the
issue): ``{{now|time}}``, ``{{today|format:%A}}``, ``{{uuid|name:cart}}``.
Tokens never span lines or contain braces. ``\\{{`` escapes a literal
``{{`` (the backslash is consumed). Unknown tokens and filters fail
loudly, naming the token and listing the vocabulary.

The module is pure: template string + context in, resolved string out.
Anything environmental — clock, user, page, query counts — arrives via
``TokenContext`` (see ``token_context.build_token_context`` for the
Django-aware wiring). ``{{count:...}}`` runs through an injected
callable; ``{{input:...}}`` reads apply-time values from
``TokenContext.inputs`` (``None`` means the binding point can't prompt,
so input tokens fail there). ``{{uuid|name:<label>}}`` returns the same
id for every occurrence of a label within one context — one template
apply shares a single context across all its blocks, which is what lets
a template wire internal references together.
"""

from __future__ import annotations

import re
import uuid as uuid_module
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Mapping, Optional

TOKEN_VOCABULARY: tuple = (
    "today",
    "now",
    "tomorrow",
    "yesterday",
    "current_date",
    "current_time",
    "page.title",
    "page.slug",
    "page.date",
    "page.url",
    "page.uuid",
    "user.email",
    "user.timezone",
    "uuid",
    "cursor",
    "input:<label>",
    "count:<query>",
)

FILTER_VOCABULARY: tuple = (
    "date",
    "time",
    "format:<strftime>",
    "name:<label>",
)

# Base tokens that take a `:arg`. Their arg is everything after the
# first colon (count queries legitimately contain colons and spaces,
# e.g. {{count:type:todo and completed is null}}).
_ARG_TOKENS = frozenset({"input", "count"})


class TokenError(ValueError):
    """A token failed to resolve. The message is user-facing; ``token``
    carries the raw ``{{...}}`` text that failed."""

    def __init__(self, message: str, token: str = "") -> None:
        super().__init__(message)
        self.token = token


@dataclass
class PageTokenContext:
    title: str
    slug: str
    uuid: str
    date: Optional[date]
    url: str


@dataclass
class UserTokenContext:
    email: str
    timezone: str
    time_format: str = "24h"


@dataclass
class TokenContext:
    """Everything the resolver may read. One instance spans one
    resolution pass — a single block save, or a whole template apply —
    so the named-uuid cache inside it defines the sharing scope of
    ``{{uuid|name:<label>}}``."""

    now: datetime
    today: date
    user: UserTokenContext
    page: PageTokenContext
    # None → this binding point cannot prompt (block save); a dict →
    # apply-time values keyed by input label (template apply).
    inputs: Optional[Mapping[str, str]] = None
    # Injected so the module stays free of query-engine imports; the
    # callable takes an inline query DSL string and returns a count.
    count_query: Optional[Callable[[str], int]] = None
    uuid_factory: Callable[[], str] = field(default=lambda: str(uuid_module.uuid4()))
    named_uuids: Dict[str, str] = field(default_factory=dict)


# Escape first so `\{{` never parses as a token; token bodies stay on
# one line and never contain braces.
_SCAN_RE = re.compile(r"\\\{\{|\{\{([^{}\n]*)\}\}")


def resolve_content_tokens(text: str, context: TokenContext) -> str:
    """Resolve every ``{{token}}`` in ``text`` against ``context``.

    Returns ``text`` unchanged when it contains no tokens. Raises
    ``TokenError`` on the first unknown or unresolvable token."""
    if not text or "{{" not in text:
        return text

    out: List[str] = []
    pos = 0
    for match in _SCAN_RE.finditer(text):
        out.append(text[pos : match.start()])
        if match.group(0).startswith("\\"):
            out.append("{{")
        else:
            out.append(_resolve_token(match.group(1), context))
        pos = match.end()
    out.append(text[pos:])
    return "".join(out)


def find_input_tokens(text: str) -> List[str]:
    """Labels of every ``{{input:<label>}}`` in ``text``, in order of
    first appearance, deduplicated. Escaped spans are skipped. Used by
    template apply to report which values it needs before resolving."""
    labels: List[str] = []
    if not text or "{{" not in text:
        return labels
    for match in _SCAN_RE.finditer(text):
        if match.group(0).startswith("\\"):
            continue
        body = match.group(1)
        base = body.split("|", 1)[0]
        name, _, arg = base.partition(":")
        if name.strip().lower() == "input":
            label = arg.strip()
            if label and label not in labels:
                labels.append(label)
    return labels


def _resolve_token(body: str, context: TokenContext) -> str:
    raw = "{{" + body + "}}"
    segments = body.split("|")
    base = segments[0]
    filters = segments[1:]

    name, colon, arg = base.partition(":")
    name = name.strip().lower()
    arg = arg.strip()

    if name in _ARG_TOKENS:
        if not arg:
            raise TokenError(
                f"`{raw}` needs an argument, e.g. `{{{{{name}:...}}}}`", raw
            )
    elif colon:
        raise TokenError(f"token `{name}` takes no argument (in `{raw}`)", raw)

    # A named uuid never draws a fresh id — the `name` filter supplies
    # the (cached) value, so don't burn one from the factory first.
    has_name_filter = any(
        segment.partition(":")[0].strip().lower() == "name" for segment in filters
    )
    if name == "uuid" and has_name_filter:
        value: Any = None
    else:
        value = _base_value(name, arg, context, raw)

    for segment in filters:
        fname, _, farg = segment.partition(":")
        value = _apply_filter(fname.strip().lower(), farg, value, name, context, raw)

    return _to_text(value, context)


def _base_value(name: str, arg: str, context: TokenContext, raw: str) -> Any:
    if name == "today" or name == "current_date":
        return context.today
    if name == "tomorrow":
        return context.today + timedelta(days=1)
    if name == "yesterday":
        return context.today - timedelta(days=1)
    if name == "now":
        return context.now
    if name == "current_time":
        return _format_time(context.now, context.user.time_format)
    if name == "page.title":
        return context.page.title
    if name == "page.slug":
        return context.page.slug
    if name == "page.uuid":
        return context.page.uuid
    if name == "page.url":
        return context.page.url
    if name == "page.date":
        # Empty rather than an error: a template carrying {{page.date}}
        # may land on a page without a date, and failing the whole
        # apply for that would be harsher than an empty slot.
        return context.page.date if context.page.date else ""
    if name == "user.email":
        return context.user.email
    if name == "user.timezone":
        return context.user.timezone
    if name == "uuid":
        return context.uuid_factory()
    if name == "cursor":
        # Snapshot semantics: the marker resolves away. Moving the
        # editor caret to this spot is frontend follow-up work.
        return ""
    if name == "input":
        if context.inputs is None:
            raise TokenError(
                f"`{raw}` only resolves when applying a template — "
                "input tokens can't be answered at block save",
                raw,
            )
        if arg not in context.inputs:
            raise TokenError(f"no value provided for `{raw}`", raw)
        return context.inputs[arg]
    if name == "count":
        if context.count_query is None:
            raise TokenError(f"`{raw}` is not available here", raw)
        try:
            return context.count_query(arg)
        except ValueError as exc:
            raise TokenError(f"`{raw}`: {exc}", raw) from exc

    raise TokenError(
        f"unknown token `{raw}` — available tokens: "
        f"{', '.join(TOKEN_VOCABULARY)}. Escape a literal {{{{ as \\{{{{",
        raw,
    )


def _apply_filter(
    fname: str,
    farg: str,
    value: Any,
    base_name: str,
    context: TokenContext,
    raw: str,
) -> Any:
    if fname == "name":
        if base_name != "uuid":
            raise TokenError(f"filter `name` only applies to `uuid` (in `{raw}`)", raw)
        label = farg.strip()
        if not label:
            raise TokenError(f"filter `name` needs a label (in `{raw}`)", raw)
        if label not in context.named_uuids:
            context.named_uuids[label] = context.uuid_factory()
        return context.named_uuids[label]
    if fname == "date":
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        raise TokenError(f"filter `date` needs a date value (in `{raw}`)", raw)
    if fname == "time":
        if isinstance(value, datetime):
            return _format_time(value, context.user.time_format)
        raise TokenError(f"filter `time` needs a date+time value (in `{raw}`)", raw)
    if fname == "format":
        if not farg:
            raise TokenError(
                f"filter `format` needs a strftime pattern (in `{raw}`)", raw
            )
        if isinstance(value, (date, datetime)):
            return value.strftime(farg)
        raise TokenError(f"filter `format` needs a date value (in `{raw}`)", raw)

    raise TokenError(
        f"unknown filter `{fname}` in `{raw}` — available filters: "
        f"{', '.join(FILTER_VOCABULARY)}",
        raw,
    )


def _format_time(value: datetime, time_format: str) -> str:
    if time_format == "12h":
        hour = value.hour % 12 or 12
        suffix = "am" if value.hour < 12 else "pm"
        return f"{hour}:{value.minute:02d}{suffix}"
    return f"{value.hour:02d}:{value.minute:02d}"


def _to_text(value: Any, context: TokenContext) -> str:
    if isinstance(value, datetime):
        return (
            f"{value.strftime('%Y-%m-%d')} "
            f"{_format_time(value, context.user.time_format)}"
        )
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
