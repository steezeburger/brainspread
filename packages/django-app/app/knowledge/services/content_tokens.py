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

Custom variables (issue #228) are user-defined tokens: ``{{name}}``
expands to the user's stored text, supplied via
``TokenContext.custom_tokens`` (name → raw expansion). Built-in names
always win — a custom variable can never shadow one. A custom
variable's expansion is itself resolved before substitution, so it may
contain built-ins (``{{current_time}} #food-log``) and other custom
variables. That nested pass is the only re-scan: a *built-in's* value is
still never re-scanned. Self and mutual references raise ``TokenError``
naming the cycle, and nesting is capped at ``MAX_CUSTOM_TOKEN_DEPTH``.

Automation action args (issue #209) reuse this same module rather than a
second parser: ``{{count}}`` (bare — the automation's matched-block
count, distinct from the existing ``{{count:<query>}}`` arg form) and a
per-block family — ``{{block.tag}}``, ``{{block.content}}``,
``{{block.uuid}}``, ``{{block.page}}``, ``{{block.due}}`` — resolved
against ``TokenContext.block`` (a ``BlockTokenContext``), one matched
block at a time. ``{{item}}`` resolves against ``TokenContext.item`` for
``for::`` iteration. ``{{block.tag}}`` collapses to a single tag only
when the block carries exactly one candidate after any ``|except:...``
filtering; zero or multiple candidates raise ``BlockTokenAmbiguousError``
(a ``TokenError`` subclass) so a caller mapping an action over many
blocks can catch it and skip just that block instead of failing the
whole run. The automation consumer additionally restricts which of this
module's tokens it accepts (see ``automation_actions.AUTOMATION_TOKEN_VOCABULARY``)
since most of the #140 vocabulary (``page.*``, ``uuid``, ``input``, …)
has no well-defined meaning across a matched-block set.
"""

from __future__ import annotations

import re
import uuid as uuid_module
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
)

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
    "count",
    "count:<query>",
    "block.tag",
    "block.content",
    "block.uuid",
    "block.page",
    "block.due",
    "item",
)

FILTER_VOCABULARY: tuple = (
    "date",
    "time",
    "format:<strftime>",
    "name:<label>",
    "except:<slug>,...",
)

# Base tokens that always take a `:arg`. Their arg is everything after
# the first colon (count queries legitimately contain colons and spaces,
# e.g. {{count:type:todo and completed is null}}).
_ARG_TOKENS = frozenset({"input"})

# Base tokens whose `:arg` is optional — bare {{count}} reads
# TokenContext.match_count (issue #209's ambient match count);
# {{count:<query>}} keeps running the injected count_query callable.
_OPTIONAL_ARG_TOKENS = frozenset({"count"})

_BLOCK_TOKEN_NAMES = frozenset(
    {"block.tag", "block.content", "block.uuid", "block.page", "block.due"}
)

# Bare names a custom variable may not take ("input:<label>" → "input").
BUILTIN_TOKEN_NAMES = frozenset(entry.split(":", 1)[0] for entry in TOKEN_VOCABULARY)

# Custom variables are hand-written aliases, so real chains are a few
# levels deep. Cycles are caught exactly by the expansion stack; this cap
# is a backstop that keeps a pathological (non-cyclic but huge) chain from
# exhausting the Python stack or blowing up the output.
MAX_CUSTOM_TOKEN_DEPTH = 10

CUSTOM_TOKEN_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class TokenError(ValueError):
    """A token failed to resolve. The message is user-facing; ``token``
    carries the raw ``{{...}}`` text that failed."""

    def __init__(self, message: str, token: str = "") -> None:
        super().__init__(message)
        self.token = token


class BlockTokenAmbiguousError(TokenError):
    """``{{block.tag}}`` (after any ``|except:...`` filtering) didn't
    resolve to exactly one candidate tag. Distinct from a plain
    ``TokenError`` so a mapped-action caller (issue #209) can catch this
    specific case and skip just the offending block, while every other
    ``TokenError`` (an unknown token, a bad filter) still aborts the
    whole run."""


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
class BlockTokenContext:
    """Plain-value snapshot of one matched block, for the ``block.*``
    token family (issue #209). Built by the Django-aware caller —
    this module stays free of model imports. ``tag_candidates`` is the
    block's own tag slugs, unfiltered; the ``except:`` filter narrows
    them at resolve time. ``content`` is the first content line with
    any state-keyword prefix (``TODO ``/``DONE ``/…) already stripped.
    ``due`` is an ISO date, or ``""`` when the block has none."""

    tag_candidates: Tuple[str, ...]
    content: str
    uuid: str
    page: str
    due: str


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
    # The user's custom variables: lowercase name → raw expansion text.
    custom_tokens: Mapping[str, str] = field(default_factory=dict)
    # Ambient match count for bare {{count}} (issue #209) — the
    # automation's matched-block total, resolved once per run. None
    # where there's no such count (e.g. block save, template apply).
    match_count: Optional[int] = None
    # The current `for::` iteration value, or None outside a for::
    # iteration — {{item}} reads this.
    item: Optional[str] = None
    # The block currently being resolved for, or None when no per-block
    # scope is active — the block.* tokens read this. A caller mapping
    # an action over many matched blocks mutates this between blocks;
    # everything else on the context (now/today/named_uuids/...) stays
    # shared across the whole run.
    block: Optional[BlockTokenContext] = None


# Escape first so `\{{` never parses as a token; token bodies stay on
# one line and never contain braces.
_SCAN_RE = re.compile(r"\\\{\{|\{\{([^{}\n]*)\}\}")


def resolve_content_tokens(text: str, context: TokenContext) -> str:
    """Resolve every ``{{token}}`` in ``text`` against ``context``.

    Returns ``text`` unchanged when it contains no tokens. Raises
    ``TokenError`` on the first unknown or unresolvable token."""
    return _resolve_text(text, context, ())


def _resolve_text(text: str, context: TokenContext, stack: Tuple[str, ...]) -> str:
    # ``stack`` holds the custom variables currently being expanded,
    # outermost first — the cycle detector reads it.
    if not text or "{{" not in text:
        return text

    out: List[str] = []
    pos = 0
    for match in _SCAN_RE.finditer(text):
        out.append(text[pos : match.start()])
        if match.group(0).startswith("\\"):
            out.append("{{")
        else:
            out.append(_resolve_token(match.group(1), context, stack))
        pos = match.end()
    out.append(text[pos:])
    return "".join(out)


def find_input_tokens(
    text: str, custom_tokens: Optional[Mapping[str, str]] = None
) -> List[str]:
    """Labels of every ``{{input:<label>}}`` in ``text``, in order of
    first appearance, deduplicated. Escaped spans are skipped. Used by
    template apply to report which values it needs before resolving.
    Looks through ``custom_tokens`` expansions too, so an input token
    nested in a custom variable still prompts."""
    labels: List[str] = []
    _collect_input_labels(text, custom_tokens or {}, labels, set())
    return labels


def _collect_input_labels(
    text: str,
    custom_tokens: Mapping[str, str],
    labels: List[str],
    seen: Set[str],
) -> None:
    for name, arg in _token_bases(text):
        if name == "input":
            if arg and arg not in labels:
                labels.append(arg)
        elif name in custom_tokens and name not in BUILTIN_TOKEN_NAMES:
            # ``seen`` stops cycles here; resolution reports them later.
            if name not in seen:
                seen.add(name)
                _collect_input_labels(custom_tokens[name], custom_tokens, labels, seen)


def find_custom_token_cycle(
    name: str, custom_tokens: Mapping[str, str]
) -> Optional[List[str]]:
    """The reference path from ``name`` back to itself through
    ``custom_tokens`` (e.g. ``["a", "b", "a"]``), or None when ``name``
    is not part of a cycle. Lets a variable be rejected at save instead
    of on first use."""

    # A variable already explored without reaching ``name`` can't reach
    # it on a second visit either.
    visited: Set[str] = {name}

    def walk(current: str, path: List[str]) -> Optional[List[str]]:
        for ref, _ in _token_bases(custom_tokens.get(current, "")):
            if ref not in custom_tokens or ref in BUILTIN_TOKEN_NAMES:
                continue
            if ref == name:
                return path + [ref]
            if ref in visited:
                continue
            visited.add(ref)
            found = walk(ref, path + [ref])
            if found:
                return found
        return None

    return walk(name, [name])


def token_names(text: str) -> List[str]:
    """Base token names (lowercased, filters stripped) referenced in
    ``text``, in order of appearance, escaped spans skipped — e.g.
    ``["block.tag", "today"]``. Lets a caller detect which tokens are
    referenced without resolving them (the automation map/``for::``
    contract checks in issue #209)."""
    return [name for name, _ in _token_bases(text)]


def _token_bases(text: str) -> Iterator[Tuple[str, str]]:
    """(lowercased name, stripped arg) of each unescaped token in ``text``."""
    if not text or "{{" not in text:
        return
    for match in _SCAN_RE.finditer(text):
        if match.group(0).startswith("\\"):
            continue
        base = match.group(1).split("|", 1)[0]
        name, _, arg = base.partition(":")
        yield name.strip().lower(), arg.strip()


def _resolve_token(body: str, context: TokenContext, stack: Tuple[str, ...]) -> str:
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
    elif name not in _OPTIONAL_ARG_TOKENS and colon:
        raise TokenError(f"token `{name}` takes no argument (in `{raw}`)", raw)

    # A named uuid never draws a fresh id — the `name` filter supplies
    # the (cached) value, so don't burn one from the factory first.
    has_name_filter = any(
        segment.partition(":")[0].strip().lower() == "name" for segment in filters
    )
    if name == "uuid" and has_name_filter:
        value: Any = None
    else:
        value = _base_value(name, arg, context, raw, stack)

    for segment in filters:
        fname, _, farg = segment.partition(":")
        value = _apply_filter(fname.strip().lower(), farg, value, name, context, raw)

    if name == "block.tag":
        # `except:` (if any) has already narrowed the candidate list —
        # this is the "fully explicit, nothing implicit" rule from the
        # issue: exactly one candidate, or the block is skipped upstream.
        candidates = value if isinstance(value, list) else [value]
        if len(candidates) != 1:
            found = ", ".join(candidates) if candidates else "(none)"
            raise BlockTokenAmbiguousError(
                f"`{raw}` needs exactly one tag after filtering — "
                f"found {len(candidates)}: {found}",
                raw,
            )
        value = candidates[0]

    return _to_text(value, context)


def _base_value(
    name: str, arg: str, context: TokenContext, raw: str, stack: Tuple[str, ...]
) -> Any:
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
        if not arg:
            if context.match_count is None:
                raise TokenError(
                    f"`{raw}` needs an argument, e.g. `{{{{count:...}}}}` — "
                    "or use bare `{{count}}` where a match count is available",
                    raw,
                )
            return context.match_count
        if context.count_query is None:
            raise TokenError(f"`{raw}` is not available here", raw)
        try:
            return context.count_query(arg)
        except ValueError as exc:
            raise TokenError(f"`{raw}`: {exc}", raw) from exc
    if name == "item":
        if context.item is None:
            raise TokenError(f"`{raw}` only resolves inside `for::` iteration", raw)
        return context.item
    if name in _BLOCK_TOKEN_NAMES:
        if context.block is None:
            raise TokenError(
                f"`{raw}` only resolves for a matched block — it needs a " "`query::`",
                raw,
            )
        if name == "block.tag":
            return list(context.block.tag_candidates)
        if name == "block.content":
            return context.block.content
        if name == "block.uuid":
            return context.block.uuid
        if name == "block.page":
            return context.block.page
        return context.block.due
    if name in context.custom_tokens:
        return _expand_custom_token(name, context, raw, stack)

    available = ", ".join(TOKEN_VOCABULARY)
    if context.custom_tokens:
        available += "; your variables: " + ", ".join(sorted(context.custom_tokens))
    raise TokenError(
        f"unknown token `{raw}` — available tokens: "
        f"{available}. Escape a literal {{{{ as \\{{{{",
        raw,
    )


def _expand_custom_token(
    name: str, context: TokenContext, raw: str, stack: Tuple[str, ...]
) -> str:
    if name in stack:
        cycle = " → ".join(stack[stack.index(name) :] + (name,))
        raise TokenError(f"custom variable cycle: {cycle}", raw)
    if len(stack) >= MAX_CUSTOM_TOKEN_DEPTH:
        raise TokenError(
            f"custom variables nested more than {MAX_CUSTOM_TOKEN_DEPTH} "
            f"deep: {' → '.join(stack + (name,))}",
            raw,
        )
    return _resolve_text(context.custom_tokens[name], context, stack + (name,))


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
    if fname == "except":
        if base_name != "block.tag":
            raise TokenError(
                f"filter `except` only applies to `block.tag` (in `{raw}`)", raw
            )
        excluded = {slug.strip() for slug in farg.split(",") if slug.strip()}
        if not excluded:
            raise TokenError(
                f"filter `except` needs at least one tag slug (in `{raw}`)", raw
            )
        return [candidate for candidate in value if candidate not in excluded]
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
