"""The action vocabulary for automations (issue #143, slice 1).

A `command` action maps a verb (e.g. ``move_to_daily``) onto an existing,
whitelisted Command and runs it over the automation's query result. This
is the declarative, zero-LLM half of the platform — the `prompt` action
(slice 2) lives elsewhere.

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

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Tuple

from django.conf import settings

from core.llm_tools import parse_relative_date
from core.models import User

from ..commands.add_template_blocks_to_page_command import (
    AddTemplateBlocksToPageCommand,
)
from ..commands.bulk_move_blocks_command import BulkMoveBlocksCommand
from ..commands.bulk_set_block_type_command import BulkSetBlockTypeCommand
from ..forms.add_template_blocks_to_page_form import AddTemplateBlocksToPageForm
from ..forms.bulk_move_blocks_form import BulkMoveBlocksForm
from ..forms.bulk_set_block_type_form import BulkSetBlockTypeForm
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


COMMAND_ACTIONS: Dict[str, ActionDef] = {
    "move_to_daily": ActionDef(handler=_move_to_daily, capability="move_to_daily"),
    "set_type": ActionDef(handler=_set_type, capability="set_type"),
    "notify": ActionDef(handler=_notify, capability="notify", requires_query=False),
    "apply_template": ActionDef(
        handler=_apply_template, capability="apply_template", requires_query=False
    ),
}
