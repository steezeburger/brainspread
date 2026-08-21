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
from typing import Callable, Dict, List, Tuple

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
from ..commands.tag_blocks_command import TagBlocksCommand, UntagBlocksCommand
from ..commands.update_block_command import UpdateBlockCommand
from ..forms.add_template_blocks_to_page_form import AddTemplateBlocksToPageForm
from ..forms.bulk_clear_schedule_form import BulkClearScheduleForm
from ..forms.bulk_move_blocks_form import BulkMoveBlocksForm
from ..forms.bulk_move_blocks_to_page_form import BulkMoveBlocksToPageForm
from ..forms.bulk_schedule_form import BulkScheduleForm
from ..forms.bulk_set_block_type_form import BulkSetBlockTypeForm
from ..forms.create_block_form import CreateBlockForm
from ..forms.tag_blocks_form import TagBlocksForm, UntagBlocksForm
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


def _resolve_tag_pages(ctx: ActionContext, args: Tuple[str, ...], verb: str):
    """Resolve tag-slug args into page uuids, strict-by-default (a missing
    tag page fails the run rather than being silently created — the same
    typo guard the MCP tag tools use)."""
    if not args:
        raise ActionError(f"`{verb}` needs at least one tag slug, e.g. `{verb} sticky`")
    page_uuids: List[str] = []
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
        page = PageRepository.get_by_slug(slug, user=ctx.user)
        if page is None:
            missing.append(slug)
        else:
            page_uuids.append(str(page.uuid))
    if missing:
        raise ActionError(
            f"tag page(s) not found: {', '.join(missing)} — create the page(s) first"
        )
    return page_uuids


def _apply_tag_verb(
    ctx: ActionContext, blocks: List[Block], args: Tuple[str, ...], *, add: bool
) -> ActionResult:
    verb = "tag" if add else "untag"
    page_uuids = _resolve_tag_pages(ctx, args, verb)
    form_cls = TagBlocksForm if add else UntagBlocksForm
    form = form_cls(
        data={
            "user": ctx.user.id,
            "block_uuids": [str(block.uuid) for block in blocks],
            "page_uuids": page_uuids,
        }
    )
    if not form.is_valid():
        raise ActionError(form.errors.as_json())
    command_cls = TagBlocksCommand if add else UntagBlocksCommand
    outcome = command_cls(form).execute()
    return ActionResult(
        affected=outcome["updated_count"],
        details=[
            {
                "updated_count": outcome["updated_count"],
                "tags": [a.strip() for a in args],
            }
        ],
    )


def _tag(
    ctx: ActionContext, blocks: List[Block], args: Tuple[str, ...]
) -> ActionResult:
    """Add page tags to every matched block, e.g. `tag needs-review`.
    Idempotent; multiple slugs allowed. Self-stopping when the query
    excludes the tag being added."""
    return _apply_tag_verb(ctx, blocks, args, add=True)


def _untag(
    ctx: ActionContext, blocks: List[Block], args: Tuple[str, ...]
) -> ActionResult:
    """Remove page tags from every matched block, e.g. `untag sticky`.
    Untagging the query's own tag is self-stopping: untagged blocks leave
    the match set."""
    return _apply_tag_verb(ctx, blocks, args, add=False)


def _set_due(
    ctx: ActionContext, blocks: List[Block], args: Tuple[str, ...]
) -> ActionResult:
    """Set (or clear) the due date on every matched block. `set_due none`
    clears due_at and any pending reminders; any date token sets an
    all-day due date."""
    if not args:
        raise ActionError(
            "`set_due` needs a date token or `none`, e.g. `set_due tomorrow`"
        )
    token = args[0].strip().lower()

    if token in {"none", "clear"}:
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

    form = BulkScheduleForm(
        data={
            "user": ctx.user.id,
            "block_uuids": [str(block.uuid) for block in blocks],
            "new_date": target.isoformat() if target else "",
        }
    )
    if not form.is_valid():
        raise ActionError(form.errors.as_json())
    outcome = BulkScheduleCommand(form).execute()
    return ActionResult(
        affected=outcome["updated_count"],
        details=[
            {
                "updated_count": outcome["updated_count"],
                "new_date": outcome["new_date"],
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
    details: List[dict] = []
    for block in blocks:
        form = UpdateBlockForm(
            data={
                "user": ctx.user.id,
                "block": str(block.uuid),
                "content": _upsert_property_line(block.content or "", key, value),
            }
        )
        if not form.is_valid():
            details.append(
                {"block_uuid": str(block.uuid), "error": form.errors.as_json()}
            )
            continue
        UpdateBlockCommand(form).execute()
        updated += 1
    details.insert(0, {"updated_count": updated, "key": key, "value": value})
    return ActionResult(affected=updated, details=details)


def _create_block(
    ctx: ActionContext, blocks: List[Block], args: Tuple[str, ...]
) -> ActionResult:
    """Standalone: `create_block "content" on <target> [as <type>]`.

    Target is explicit — a date token (daily page, created if needed) or
    a page reference (title / slug / [[wiki]]); no silent defaulting.
    """
    if not args or not args[0].strip():
        raise ActionError(
            "`create_block` needs content, e.g. "
            'create_block "review inbox" on today as todo'
        )
    content = args[0]

    rest = list(args[1:])
    block_type = "bullet"
    if len(rest) >= 2 and rest[-2].lower() == "as":
        block_type = rest[-1].lower()
        rest = rest[:-2]
        valid_types = {c[0] for c in Block._meta.get_field("block_type").choices}
        if block_type not in valid_types:
            raise ActionError(
                f"unknown block type `{block_type}` "
                f"(expected one of: {', '.join(sorted(valid_types))})"
            )
    if len(rest) < 2 or rest[0].lower() != "on":
        raise ActionError(
            'expected `create_block "<content>" on <date|page> [as <type>]` '
            "— the target page is always explicit"
        )
    target_tokens = tuple(rest[1:])

    try:
        target_date = parse_relative_date(" ".join(target_tokens), ctx.user.today())
    except ValueError:
        target_date = None

    if target_date is not None:
        page, _ = PageRepository.get_or_create_daily_note(ctx.user, target_date)
    else:
        page = _resolve_target_page(ctx, target_tokens, "create_block")

    form = CreateBlockForm(
        data={
            "user": ctx.user.id,
            "page": str(page.uuid),
            "content": content,
            "block_type": block_type,
        }
    )
    if not form.is_valid():
        raise ActionError(form.errors.as_json())
    block = CreateBlockCommand(form).execute()
    return ActionResult(
        affected=1,
        details=[
            {
                "block_uuid": str(block.uuid),
                "target_page_uuid": str(page.uuid),
                "block_type": block_type,
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
