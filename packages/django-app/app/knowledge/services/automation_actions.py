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

from core.llm_tools import parse_relative_date
from core.models import User

from ..commands.bulk_move_blocks_command import BulkMoveBlocksCommand
from ..commands.bulk_set_block_type_command import BulkSetBlockTypeCommand
from ..forms.bulk_move_blocks_form import BulkMoveBlocksForm
from ..forms.bulk_set_block_type_form import BulkSetBlockTypeForm
from ..models import Block
from .automation_spec import ActionSpec


class ActionError(ValueError):
    """An action couldn't run — bad args, failed validation, or a missing
    capability. Recorded on the AutomationRun as the failure reason."""


@dataclass(frozen=True)
class ActionContext:
    user: User
    allow: frozenset
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


COMMAND_ACTIONS: Dict[str, ActionDef] = {
    "move_to_daily": ActionDef(handler=_move_to_daily, capability="move_to_daily"),
    "set_type": ActionDef(handler=_set_type, capability="set_type"),
}
