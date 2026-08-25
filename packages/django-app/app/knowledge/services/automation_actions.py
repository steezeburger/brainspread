"""The action vocabulary for automations (issues #143 / #199).

A `command` action maps a verb (e.g. ``move_to_daily``) onto an existing,
whitelisted Command and runs it over the automation's query result. This
is the declarative, zero-LLM half of the platform — the `prompt` action
(#199 slice 2) lives elsewhere. The vocabulary mirrors the block data
model's axes (location, type, tags, due, properties, existence) and is
deliberately closed: workflows are new trigger × query × verb
combinations, and the long tail belongs to ``prompt`` / ``http`` and,
eventually, user-defined handlers (#193).

Handlers receive the whole matched batch and delegate to the app's bulk
commands, which own the batch semantics — notably ``BulkMoveBlocksCommand``
keeps selected sub-blocks riding along with their selected ancestors
instead of double-moving (and detaching) them.

Each verb declares the capability token it requires; the run only executes
it when that token is in the automation's ``allow::`` list. That keeps the
"writes are explicit" guarantee uniform with the prompt-action approval
model, and means a definition can't silently grow new powers by editing
only the ``action::`` line. Verbs also declare ``requires_query`` so the
run command can reject a query-less spec for set actions while leaving
room for standalone actions (``apply_template``, bare ``notify``) that
run without a result set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from django.conf import settings

from core.llm_tools import parse_relative_date
from core.models import User

from ..commands.add_template_blocks_to_page_command import (
    AddTemplateBlocksToPageCommand,
)
from ..commands.bulk_clear_schedule_command import BulkClearScheduleCommand
from ..commands.bulk_move_blocks_command import BulkMoveBlocksCommand
from ..commands.bulk_move_blocks_to_page_command import BulkMoveBlocksToPageCommand
from ..commands.bulk_schedule_command import BulkScheduleCommand
from ..commands.bulk_set_block_type_command import BulkSetBlockTypeCommand
from ..commands.create_block_command import CreateBlockCommand
from ..commands.schedule_block_command import ScheduleBlockCommand
from ..commands.set_block_type_command import STATE_PREFIXES
from ..commands.tag_blocks_command import UntagBlocksCommand
from ..commands.update_block_command import UpdateBlockCommand
from ..forms.add_template_blocks_to_page_form import AddTemplateBlocksToPageForm
from ..forms.bulk_clear_schedule_form import BulkClearScheduleForm
from ..forms.bulk_move_blocks_form import BulkMoveBlocksForm
from ..forms.bulk_move_blocks_to_page_form import BulkMoveBlocksToPageForm
from ..forms.bulk_schedule_form import BulkScheduleForm
from ..forms.bulk_set_block_type_form import BulkSetBlockTypeForm
from ..forms.create_block_form import CreateBlockForm
from ..forms.schedule_block_form import ScheduleBlockForm
from ..forms.tag_blocks_form import UntagBlocksForm
from ..forms.update_block_form import UpdateBlockForm
from ..models import Block
from ..repositories.page_repository import PageRepository
from .automation_spec import ActionSpec
from .block_links import block_page_url
from .discord_webhook import post_webhook


class ActionError(ValueError):
    """An action couldn't run — bad args, failed validation, or a missing
    capability. Recorded on the AutomationRun as the failure reason."""


@dataclass(frozen=True)
class ActionContext:
    user: User
    allow: frozenset
    # Whether the automation declared a query::. Lets a dual-mode action
    # like `notify` distinguish "query matched nothing → stay quiet" from
    # "no query at all → send the bare message".
    has_query: bool = False
    origin: str = "automation"


@dataclass
class ActionResult:
    affected: int = 0
    details: List[dict] = field(default_factory=list)


ActionHandler = Callable[["ActionContext", List[Block], Tuple[str, ...]], ActionResult]


@dataclass(frozen=True)
class ActionDef:
    handler: ActionHandler
    capability: str
    # Set actions consume the automation's query result; standalone
    # actions (future: apply_template, bare notify) run without one.
    requires_query: bool = True


def resolve_action(verb: str) -> ActionDef:
    """Look up a verb's ActionDef. Raises ``ActionError`` for unknown verbs
    so misconfigured automations fail with the available vocabulary."""
    action_def = COMMAND_ACTIONS.get(verb)
    if action_def is None:
        raise ActionError(
            f"unknown action `{verb}` "
            f"(available: {', '.join(sorted(COMMAND_ACTIONS))})"
        )
    return action_def


def run_action(
    action: ActionSpec, ctx: ActionContext, blocks: List[Block]
) -> ActionResult:
    """Run ``action`` over the matched ``blocks``.

    Raises ``ActionError`` (before touching any block) when the verb is
    unknown or its capability isn't granted, so a misconfigured automation
    fails cleanly instead of half-applying."""
    action_def = resolve_action(action.verb)
    if action_def.capability not in ctx.allow:
        raise ActionError(
            f"action `{action.verb}` is not in the automation's "
            f"`allow::` list (add `{action_def.capability}`)"
        )

    if action_def.requires_query and not blocks:
        return ActionResult()

    return action_def.handler(ctx, blocks, action.args)


def _move_to_daily(
    ctx: ActionContext, blocks: List[Block], args: Tuple[str, ...]
) -> ActionResult:
    raw = args[0] if args else "today"
    try:
        target = parse_relative_date(raw, ctx.user.today())
    except ValueError as exc:
        raise ActionError(str(exc)) from exc

    form = BulkMoveBlocksForm(
        data={
            "user": ctx.user.id,
            "blocks": [str(block.uuid) for block in blocks],
            "target_date": target.isoformat() if target else "",
        }
    )
    if not form.is_valid():
        raise ActionError(form.errors.as_json())
    outcome = BulkMoveBlocksCommand(form).execute()
    return ActionResult(
        affected=outcome["moved_count"],
        details=[
            {
                "moved_count": outcome["moved_count"],
                "skipped_count": outcome["skipped_count"],
                "target_page_uuid": outcome["target_page"]["uuid"],
            }
        ],
    )


def _set_type(
    ctx: ActionContext, blocks: List[Block], args: Tuple[str, ...]
) -> ActionResult:
    if not args:
        raise ActionError("`set_type` needs a block type, e.g. `set_type done`")
    new_type = args[0].lower()
    form = BulkSetBlockTypeForm(
        data={
            "user": ctx.user.id,
            "block_uuids": [str(block.uuid) for block in blocks],
            "new_type": new_type,
        }
    )
    if not form.is_valid():
        raise ActionError(form.errors.as_json())
    outcome = BulkSetBlockTypeCommand(form).execute()
    return ActionResult(
        affected=outcome["updated_count"],
        details=[
            {
                "updated_count": outcome["updated_count"],
                "failed": outcome["failed"],
                "block_type": new_type,
            }
        ],
    )


# Tolerated sugar on page-target args: `move_to_page [[Groceries]]` reads
# naturally in the graph and stays forward-compatible with a wiki-link
# autocomplete, but plain `"title"` / `slug` args work identically.
_WIKI_REF_RE = re.compile(r"^\[\[(.+)\]\]$")


def _resolve_target_page(ctx: ActionContext, args: Tuple[str, ...], verb: str):
    if not args:
        raise ActionError(f'`{verb}` needs a target page, e.g. {verb} "groceries"')
    raw = " ".join(args).strip()
    m = _WIKI_REF_RE.match(raw)
    ref = (m.group(1) if m else raw).strip()
    if not ref:
        raise ActionError(f"`{verb}` needs a non-empty page reference")
    page = PageRepository.get_by_title_or_slug(ctx.user, ref)
    if page is None:
        raise ActionError(f"page `{ref}` not found")
    if page.page_type == "template":
        raise ActionError(
            f"`{ref}` is a template — moving blocks into a template would "
            "hide them from views; use apply_template to copy the other way"
        )
    return page


def _move_to_page(
    ctx: ActionContext, blocks: List[Block], args: Tuple[str, ...]
) -> ActionResult:
    """Move matched blocks (with their subtrees) to an explicit page,
    referenced by title, slug, or [[wiki-link]] sugar."""
    page = _resolve_target_page(ctx, args, "move_to_page")
    form = BulkMoveBlocksToPageForm(
        data={
            "user": ctx.user.id,
            "blocks": [str(block.uuid) for block in blocks],
            "target_page": str(page.uuid),
        }
    )
    if not form.is_valid():
        raise ActionError(form.errors.as_json())
    outcome = BulkMoveBlocksToPageCommand(form).execute()
    return ActionResult(
        affected=outcome["moved_count"],
        details=[
            {
                "moved_count": outcome["moved_count"],
                "skipped_count": outcome["skipped_count"],
                "target_page_uuid": str(page.uuid),
            }
        ],
    )


# Cap how many block lines ride in a notify embed; Discord embeds top out
# well above this, but a nudge listing 500 items is noise, not a nudge.
_NOTIFY_MAX_LINES = 10

# Per-line text cap keeps a 10-line embed inside Discord's 4096-char
# description limit even with the link markup included.
_NOTIFY_LINE_CHARS = 90


def _notify_line(block: Block, site_url: str) -> str:
    """One embed line per matched block — a deep link into the app when
    SITE_URL is a real http(s) URL, plain text otherwise."""
    text = block.first_content_line() or "(untitled block)"
    if len(text) > _NOTIFY_LINE_CHARS:
        text = text[: _NOTIFY_LINE_CHARS - 1] + "…"
    url = block_page_url(block, site_url)
    if url:
        # Square brackets in content would break the markdown link.
        safe = text.replace("[", "(").replace("]", ")")
        return f"• [{safe}]({url})"
    return f"• {text}"


def _notify(
    ctx: ActionContext, blocks: List[Block], args: Tuple[str, ...]
) -> ActionResult:
    """Dual-mode Discord nudge. With a query: one message listing the
    matched blocks — and silence when nothing matches, which is what makes
    a `type:doing` nudge self-stopping. Without a query: the bare message
    (e.g. `trash night`)."""
    if not args or not args[0].strip():
        raise ActionError('`notify` needs a message, e.g. notify "still on this?"')
    message = args[0].strip()

    if ctx.has_query and not blocks:
        return ActionResult(
            affected=0, details=[{"sent": False, "reason": "no matches"}]
        )

    url = ctx.user.discord_webhook_url
    if not url:
        raise ActionError("no Discord webhook configured for this user")

    embed: dict = {"title": message[:240], "footer": {"text": "Automation"}}
    if blocks:
        lines = [
            _notify_line(block, settings.SITE_URL)
            for block in blocks[:_NOTIFY_MAX_LINES]
        ]
        if len(blocks) > _NOTIFY_MAX_LINES:
            lines.append(f"…and {len(blocks) - _NOTIFY_MAX_LINES} more")
        embed["description"] = "\n".join(lines)

    content = f"<@{ctx.user.discord_user_id}>" if ctx.user.discord_user_id else ""
    result = post_webhook(url, content, embeds=[embed])
    if not result.ok:
        raise ActionError(f"notify delivery failed: {result.error}")

    return ActionResult(
        affected=len(blocks) if ctx.has_query else 1,
        details=[{"sent": True, "blocks": len(blocks)}],
    )


def _apply_template(
    ctx: ActionContext, blocks: List[Block], args: Tuple[str, ...]
) -> ActionResult:
    """Standalone action: copy a template's block tree onto a daily page,
    e.g. `apply_template "morning routine" to today`. Target defaults to
    today's daily; the query result is ignored."""
    if not args or not args[0].strip():
        raise ActionError(
            "`apply_template` needs a template name, e.g. "
            'apply_template "morning routine" to today'
        )
    name = args[0].strip()

    if len(args) == 1:
        target_token = "today"
    elif len(args) == 3 and args[1].lower() == "to":
        target_token = args[2]
    else:
        raise ActionError('expected `apply_template "<template name>" [to <date>]`')

    try:
        target_date = parse_relative_date(target_token, ctx.user.today())
    except ValueError as exc:
        raise ActionError(str(exc)) from exc

    template = PageRepository.get_template_by_title(ctx.user, name)
    if template is None:
        raise ActionError(f"template `{name}` not found")

    target_page, _ = PageRepository.get_or_create_daily_note(ctx.user, target_date)

    form = AddTemplateBlocksToPageForm(
        data={
            "user": ctx.user.id,
            "template": str(template.uuid),
            "target_page": str(target_page.uuid),
        }
    )
    if not form.is_valid():
        raise ActionError(form.errors.as_json())
    outcome = AddTemplateBlocksToPageCommand(form).execute()
    return ActionResult(
        affected=outcome["added"],
        details=[
            {
                "added": outcome["added"],
                "template": template.title,
                "target_page_uuid": outcome["target_page"]["uuid"],
            }
        ],
    )


def _resolve_tag_slugs(
    ctx: ActionContext, args: Tuple[str, ...], verb: str
) -> List[str]:
    """Validate tag-slug args, strict-by-default: every slug must already
    exist as a page (a missing one fails the run rather than being
    silently created — the same typo guard the MCP tag tools use)."""
    if not args:
        raise ActionError(f"`{verb}` needs at least one tag slug, e.g. `{verb} sticky`")
    slugs: List[str] = []
    missing: List[str] = []
    for raw in args:
        slug = raw.strip()
        if slug.startswith("#"):
            # Mirrors the query DSL's hashtag guard: a literal `#x` in the
            # action:: line would tag the automation block itself.
            raise ActionError(
                f"use `{verb} {slug.lstrip('#')}` — a literal `#` in the "
                "action line would tag the automation block itself"
            )
        if not slug:
            raise ActionError(f"`{verb}` got an empty tag slug")
        if PageRepository.get_by_slug(slug, user=ctx.user) is None:
            missing.append(slug)
        else:
            slugs.append(slug)
    if missing:
        raise ActionError(
            f"tag page(s) not found: {', '.join(missing)} — create the page(s) first"
        )
    return slugs


def _tag_occurrence_re(slug: str) -> re.Pattern:
    """Matches a live ``#slug`` occurrence in block content — the same
    shape the tag sync scans for (backslash-escaped ``\\#slug`` excluded,
    no partial-slug matches)."""
    return re.compile(rf"(?<!\\)#{re.escape(slug)}(?![A-Za-z0-9_-])")


def _update_block_content(ctx: ActionContext, block: Block, content: str) -> None:
    """Rewrite a block's content the way the editor would.

    UpdateBlockCommand auto-detects block type from a state-keyword
    prefix (``TODO ``/``DONE ``/…) because the editor always submits
    one for todo-family blocks — content without it demotes the block
    to ``bullet`` and clears ``completed_at``. Blocks whose type was
    set via commands/tools store bare content, so an automation rewrite
    must re-assert the prefix or a `done` block silently loses its
    completion the moment a verb touches its text."""
    prefix = STATE_PREFIXES.get(block.block_type)
    if prefix and not content.lstrip().lower().startswith(prefix.lower()):
        content = f"{prefix} {content.lstrip()}"
    form = UpdateBlockForm(
        data={"user": ctx.user.id, "block": str(block.uuid), "content": content}
    )
    if not form.is_valid():
        raise ActionError(form.errors.as_json())
    UpdateBlockCommand(form).execute()


def _tag(
    ctx: ActionContext, blocks: List[Block], args: Tuple[str, ...]
) -> ActionResult:
    """Append ``#slug`` hashtags to each matched block's first content
    line, e.g. `tag needs-review`. Tags must live in content to be
    durable: the content↔tag sync removes M2M links whose hashtag isn't
    present on every content edit, so a link-only tag would silently
    vanish the next time the block is touched. Idempotent; multiple
    slugs allowed."""
    slugs = _resolve_tag_slugs(ctx, args, "tag")
    updated = 0
    for block in blocks:
        content = block.content or ""
        to_add = [s for s in slugs if not _tag_occurrence_re(s).search(content)]
        if not to_add:
            continue
        lines = content.split("\n")
        suffix = " ".join(f"#{s}" for s in to_add)
        lines[0] = f"{lines[0].rstrip()} {suffix}".strip()
        _update_block_content(ctx, block, "\n".join(lines))
        updated += 1
    return ActionResult(
        affected=updated,
        details=[{"updated_count": updated, "tags": slugs}],
    )


def _untag(
    ctx: ActionContext, blocks: List[Block], args: Tuple[str, ...]
) -> ActionResult:
    """Remove tags from every matched block, e.g. `untag sticky` — strips
    ``#slug`` from content (the sync then drops the page link) and removes
    any content-less link directly, so both authoring styles untag
    durably. Untagging the query's own tag is self-stopping: untagged
    blocks leave the match set."""
    slugs = _resolve_tag_slugs(ctx, args, "untag")
    affected = 0
    for block in blocks:
        content = block.content or ""
        had_tag = bool(set(slugs) & set(block.get_tag_names()))
        new_content = content
        for slug in slugs:
            new_content = _tag_occurrence_re(slug).sub("", new_content)
        if new_content != content:
            new_content = re.sub(r"[ \t]{2,}", " ", new_content)
            new_content = "\n".join(line.rstrip() for line in new_content.split("\n"))
            _update_block_content(ctx, block, new_content)
            affected += 1
        elif had_tag:
            affected += 1

    # Content-less links (added via block.pages directly) aren't touched
    # by the content sync — drop them explicitly. Idempotent for the rest.
    page_uuids: List[str] = []
    for slug in slugs:
        page = PageRepository.get_by_slug(slug, user=ctx.user)
        if page is not None:
            page_uuids.append(str(page.uuid))
    if page_uuids and blocks:
        form = UntagBlocksForm(
            data={
                "user": ctx.user.id,
                "block_uuids": [str(block.uuid) for block in blocks],
                "page_uuids": page_uuids,
            }
        )
        if not form.is_valid():
            raise ActionError(form.errors.as_json())
        UntagBlocksCommand(form).execute()

    return ActionResult(
        affected=affected,
        details=[{"updated_count": affected, "tags": slugs}],
    )


def _set_due(
    ctx: ActionContext, blocks: List[Block], args: Tuple[str, ...]
) -> ActionResult:
    """Set (or clear) the due date on every matched block.

    Grammar: `set_due <date> [HH:MM] [remind [<date>] <HH:MM>]…` |
    `set_due none`. A bare date is all-day; a time sets due_at_has_time;
    each repeatable `remind` clause adds one reminder (dateless = on the
    due date), replacing the block's pending set. `none`/`clear` drops
    due_at and pending reminders."""
    if not args:
        raise ActionError(
            "`set_due` needs a date token or `none`, e.g. `set_due tomorrow`"
        )
    token = args[0].strip().lower()

    if token in {"none", "clear"}:
        if len(args) > 1:
            raise ActionError("`set_due none` takes no further arguments")
        clear_form = BulkClearScheduleForm(
            data={
                "user": ctx.user.id,
                "block_uuids": [str(block.uuid) for block in blocks],
            }
        )
        if not clear_form.is_valid():
            raise ActionError(clear_form.errors.as_json())
        outcome = BulkClearScheduleCommand(clear_form).execute()
        return ActionResult(
            affected=outcome["cleared_count"],
            details=[{"cleared_count": outcome["cleared_count"]}],
        )

    try:
        target = parse_relative_date(token, ctx.user.today())
    except ValueError as exc:
        raise ActionError(str(exc)) from exc

    rest = [a.strip() for a in args[1:]]
    due_time: Optional[str] = None
    if rest and _CLAUSE_TIME_RE.match(rest[0]):
        due_time = rest.pop(0)
    reminders: List[dict] = []
    while rest:
        if rest.pop(0).lower() != "remind":
            raise ActionError(
                "expected `set_due <date> [HH:MM] [remind [<date>] <HH:MM>]…` "
                "or `set_due none`"
            )
        spec: List[str] = []
        while rest and rest[0].lower() != "remind" and len(spec) < 2:
            spec.append(rest.pop(0))
        reminders.append(_parse_remind_spec(ctx, spec))

    data = {
        "user": ctx.user.id,
        "block_uuids": [str(block.uuid) for block in blocks],
        "new_date": target.isoformat() if target else "",
    }
    if due_time is not None:
        data["new_time"] = due_time
    if reminders:
        data["reminders"] = reminders
    form = BulkScheduleForm(data=data)
    if not form.is_valid():
        raise ActionError(form.errors.as_json())
    outcome = BulkScheduleCommand(form).execute()
    return ActionResult(
        affected=outcome["updated_count"],
        details=[
            {
                "updated_count": outcome["updated_count"],
                "new_date": outcome["new_date"],
                "new_time": due_time,
                "reminders": reminders,
            }
        ],
    )


# Property keys share the charset the content-property parser accepts, so
# the `key:: value` line we write is guaranteed to round-trip through
# extract_properties_from_content.
_PROPERTY_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _upsert_property_line(content: str, key: str, value: str) -> str:
    """Replace an existing line-start ``key:: …`` line, or append one.

    Properties must live in content: extract_properties_from_content
    re-syncs the properties dict from content on every edit, so a
    dict-only write would silently evaporate on the block's next save.
    Line-start properties take precedence over inline ones during
    extraction, so appending also effectively overrides an inline value.
    """
    line_re = re.compile(rf"^{re.escape(key)}::\s*.*$", re.MULTILINE)
    new_line = f"{key}:: {value}"
    if line_re.search(content or ""):
        return line_re.sub(new_line, content, count=1)
    if not content:
        return new_line
    return f"{content}\n{new_line}"


def _set_property(
    ctx: ActionContext, blocks: List[Block], args: Tuple[str, ...]
) -> ActionResult:
    """`set_property <key> <value>` — write the ``key:: value`` line into
    each matched block's content (quoted values keep spaces). Routed
    through UpdateBlockCommand so tag/property syncing stays uniform."""
    if len(args) != 2:
        raise ActionError(
            "`set_property` expects `set_property <key> <value>`, e.g. "
            "set_property priority high — quote multi-word values"
        )
    key, value = args[0].strip(), args[1].strip()
    if not _PROPERTY_KEY_RE.match(key):
        raise ActionError(
            f"bad property key `{key}` (letters, digits, `_` and `-` only)"
        )
    if not value:
        raise ActionError("`set_property` needs a non-empty value")

    updated = 0
    for block in blocks:
        _update_block_content(
            ctx, block, _upsert_property_line(block.content or "", key, value)
        )
        updated += 1
    return ActionResult(
        affected=updated,
        details=[{"updated_count": updated, "key": key, "value": value}],
    )


def _parse_remind_spec(ctx: ActionContext, tokens: List[str]) -> dict:
    """One `remind [<date>] <HH:MM>` clause → a reminder entry for the
    schedule forms. A dateless entry fires on the due date; date tokens
    mean what they mean everywhere else in the grammar (relative to the
    run date), so "the day before a +7d due" is `remind +6d 18:00`."""
    if len(tokens) == 1 and _CLAUSE_TIME_RE.match(tokens[0]):
        return {"time": tokens[0]}
    if len(tokens) == 2 and _CLAUSE_TIME_RE.match(tokens[1]):
        try:
            date_value = parse_relative_date(tokens[0], ctx.user.today())
        except ValueError as exc:
            raise ActionError(str(exc)) from exc
        # parse_relative_date returns None (not ValueError) for blank
        # input — a quoted empty token would otherwise crash on
        # .isoformat() below.
        if date_value is None:
            raise ActionError(f"unrecognized date token {tokens[0]!r} in `remind`")
        return {"date": date_value.isoformat(), "time": tokens[1]}
    raise ActionError(
        "`remind` expects `[<date>] <HH:MM>`, e.g. `remind 7:30` or "
        "`remind +6d 18:00`"
    )


# Clause keywords for the create_block grammar. Everything after the
# content arg is sectioned by these; each collects tokens until the next.
_CREATE_BLOCK_KEYWORDS = ("on", "as", "tagged", "with", "due", "remind")

_CREATE_BLOCK_USAGE = (
    'expected `create_block "<content>" on <date|page> [as <type>] '
    "[tagged <slug> …] [with key=value …] [due <date|HH:MM|date HH:MM>] "
    "[remind [<date>] <HH:MM>]…`"
)

# User-local wall-clock time for the due/remind clauses (24h, minutes
# required) — same shape the schedule cadences accept.
_CLAUSE_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _create_block(
    ctx: ActionContext, blocks: List[Block], args: Tuple[str, ...]
) -> ActionResult:
    """Standalone: `create_block "content" on <target> [as <type>]
    [tagged <slug> …] [with key=value …]`.

    Target is explicit — a date token (daily page, created if needed) or
    a page reference (title / slug / [[wiki]]); no silent defaulting.
    Tags and properties are ARGS, never content syntax: a bare `#x` or
    `key:: value` inside the quoted content would be picked up by the
    automation definition block's own tag/property sync and contaminate
    the definition, so both are rejected with a pointer to the clause
    that does it safely. The clauses write the canonical durable forms
    onto the created block (`#slug` on the first line, `key:: value`
    lines after), which its own sync then links up.
    """
    if not args or not args[0].strip():
        raise ActionError(
            "`create_block` needs content, e.g. "
            'create_block "review inbox" on today as todo'
        )
    content = args[0]
    if re.search(r"(?<!\\)#", content):
        raise ActionError(
            "no bare `#` in create_block content — it would tag the "
            "automation definition itself; use `tagged <slug>` "
            "(or escape a literal hash as `\\#`)"
        )
    if "::" in content:
        raise ActionError(
            "no `key:: value` in create_block content — it would become a "
            "property of the automation definition; use `with key=value`"
        )

    sections: Dict[str, List[str]] = {}
    # `remind` is repeatable (one clause per reminder, like the app's
    # reminder list); every other keyword appears at most once.
    remind_specs: List[List[str]] = []
    current: Optional[List[str]] = None
    for token in args[1:]:
        lowered = token.lower()
        if lowered == "remind":
            remind_specs.append([])
            current = remind_specs[-1]
        elif lowered in _CREATE_BLOCK_KEYWORDS:
            if lowered in sections:
                raise ActionError(
                    f"duplicate `{lowered}` clause — {_CREATE_BLOCK_USAGE}"
                )
            sections[lowered] = []
            current = sections[lowered]
        else:
            if current is None:
                raise ActionError(
                    f"{_CREATE_BLOCK_USAGE} — the target page is always explicit"
                )
            current.append(token)

    target_tokens = tuple(sections.get("on") or ())
    if not target_tokens:
        raise ActionError(f"{_CREATE_BLOCK_USAGE} — the target page is always explicit")

    block_type = "bullet"
    if "as" in sections:
        if len(sections["as"]) != 1:
            raise ActionError("`as` expects exactly one block type")
        block_type = sections["as"][0].lower()
        valid_types = {c[0] for c in Block._meta.get_field("block_type").choices}
        if block_type not in valid_types:
            raise ActionError(
                f"unknown block type `{block_type}` "
                f"(expected one of: {', '.join(sorted(valid_types))})"
            )

    tag_slugs: List[str] = []
    if "tagged" in sections:
        tag_slugs = _resolve_tag_slugs(
            ctx, tuple(sections["tagged"]), "create_block tagged"
        )

    props: List[Tuple[str, str]] = []
    if "with" in sections:
        if not sections["with"]:
            raise ActionError("`with` expects key=value pairs")
        for pair in sections["with"]:
            key, sep, value = pair.partition("=")
            key, value = key.strip(), value.strip()
            if not sep or not _PROPERTY_KEY_RE.match(key) or not value:
                raise ActionError(
                    f"bad `with` pair `{pair}` — expected key=value "
                    '(quote multi-word values: status="in review")'
                )
            props.append((key, value))

    try:
        target_date = parse_relative_date(" ".join(target_tokens), ctx.user.today())
    except ValueError:
        target_date = None

    due_date = None
    due_time: Optional[str] = None
    if "due" in sections:
        due_tokens = sections["due"]
        if not due_tokens or len(due_tokens) > 2:
            raise ActionError(
                "`due` expects `due <date>`, `due <HH:MM>`, or `due <date> <HH:MM>`"
            )
        if len(due_tokens) == 1 and _CLAUSE_TIME_RE.match(due_tokens[0]):
            # Bare time: the date comes from the explicit `on <date>` target.
            if target_date is None:
                raise ActionError(
                    "`due <HH:MM>` needs a date when the target is a page — "
                    "use `due <date> <HH:MM>`"
                )
            due_date, due_time = target_date, due_tokens[0]
        else:
            try:
                due_date = parse_relative_date(due_tokens[0], ctx.user.today())
            except ValueError as exc:
                raise ActionError(str(exc)) from exc
            # None (blank token) would silently skip scheduling below —
            # an explicit `due` clause must set a date or fail loudly.
            if due_date is None:
                raise ActionError(f"unrecognized date token {due_tokens[0]!r} in `due`")
            if len(due_tokens) == 2:
                if not _CLAUSE_TIME_RE.match(due_tokens[1]):
                    raise ActionError(
                        f"bad time `{due_tokens[1]}` in `due` clause (expected HH:MM)"
                    )
                due_time = due_tokens[1]

    reminders: List[dict] = []
    if remind_specs:
        if due_date is None:
            raise ActionError(
                "`remind` requires a `due` clause — reminders anchor to " "the due date"
            )
        for spec in remind_specs:
            reminders.append(_parse_remind_spec(ctx, spec))

    if target_date is not None:
        page, _ = PageRepository.get_or_create_daily_note(ctx.user, target_date)
    else:
        page = _resolve_target_page(ctx, target_tokens, "create_block")

    final_content = content
    if tag_slugs:
        lines = final_content.split("\n")
        suffix = " ".join(f"#{s}" for s in tag_slugs)
        lines[0] = f"{lines[0].rstrip()} {suffix}".strip()
        final_content = "\n".join(lines)
    for key, value in props:
        final_content = _upsert_property_line(final_content, key, value)

    form = CreateBlockForm(
        data={
            "user": ctx.user.id,
            "page": str(page.uuid),
            "content": final_content,
            "block_type": block_type,
        }
    )
    if not form.is_valid():
        raise ActionError(form.errors.as_json())
    block = CreateBlockCommand(form).execute()

    if due_date is not None:
        schedule_data = {
            "user": ctx.user.id,
            "block": str(block.uuid),
            "due_date": due_date.isoformat(),
        }
        if due_time is not None:
            schedule_data["due_time"] = due_time
        if reminders:
            schedule_data["reminders"] = reminders
        schedule_form = ScheduleBlockForm(data=schedule_data)
        if not schedule_form.is_valid():
            raise ActionError(schedule_form.errors.as_json())
        block = ScheduleBlockCommand(schedule_form).execute()

    return ActionResult(
        affected=1,
        details=[
            {
                "block_uuid": str(block.uuid),
                "target_page_uuid": str(page.uuid),
                "block_type": block_type,
                "tags": tag_slugs,
                "properties": dict(props),
                "due_date": due_date.isoformat() if due_date else None,
                "due_time": due_time,
                "reminders": reminders,
            }
        ],
    )


COMMAND_ACTIONS: Dict[str, ActionDef] = {
    "move_to_daily": ActionDef(handler=_move_to_daily, capability="move_to_daily"),
    "move_to_page": ActionDef(handler=_move_to_page, capability="move_to_page"),
    "set_type": ActionDef(handler=_set_type, capability="set_type"),
    "tag": ActionDef(handler=_tag, capability="tag"),
    "untag": ActionDef(handler=_untag, capability="untag"),
    "set_due": ActionDef(handler=_set_due, capability="set_due"),
    "set_property": ActionDef(handler=_set_property, capability="set_property"),
    "create_block": ActionDef(
        handler=_create_block, capability="create_block", requires_query=False
    ),
    "notify": ActionDef(handler=_notify, capability="notify", requires_query=False),
    "apply_template": ActionDef(
        handler=_apply_template, capability="apply_template", requires_query=False
    ),
}
