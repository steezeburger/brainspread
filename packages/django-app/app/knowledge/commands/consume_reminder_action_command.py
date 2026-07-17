from datetime import timedelta
from typing import Optional, TypedDict

from django.db import transaction
from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.consume_reminder_action_form import ConsumeReminderActionForm
from ..forms.move_block_to_daily_form import MoveBlockToDailyForm
from ..forms.set_block_type_form import SetBlockTypeForm
from ..models import Block, Reminder, ReminderAction
from .move_block_to_daily_command import MoveBlockToDailyCommand
from .set_block_type_command import SetBlockTypeCommand


class ConsumeReminderActionData(TypedDict):
    status: str
    action: Optional[str]
    block_uuid: Optional[str]
    page_slug: Optional[str]
    detail: str


class ConsumeReminderActionCommand(AbstractBaseCommand):
    """Resolve and execute a reminder action token.

    The webhook reply view hands a raw `token` here. Outcomes:
    - `executed` — token was valid and the action ran. `block_uuid`
      and `page_slug` are populated so the view can build a "back to
      block" link.
    - `not_found` — no row for this token. Likely a typo or a token
      from before this feature shipped.
    - `expired` — token is past its `expires_at`. We don't extend.
    - `already_used` — token was consumed already (single-use).
    - `block_completed` — the block transitioned to a terminal state
      (done/wontdo) before the user clicked. We treat this as a
      no-op success: there's nothing useful left to do, and snoozing
      a finished todo would be confusing.

    The whole consume runs in a transaction so the action mutation
    and `mark_used` flip atomically — no half-applied side effects
    if the inner command raises.
    """

    def __init__(self, form: ConsumeReminderActionForm) -> None:
        self.form = form

    def execute(self) -> ConsumeReminderActionData:
        super().execute()

        token: str = self.form.cleaned_data["token"]
        now = self.form.cleaned_data.get("now") or timezone.now()

        try:
            action_row: ReminderAction = ReminderAction.objects.select_related(
                "reminder", "reminder__block", "reminder__block__page"
            ).get(token=token)
        except ReminderAction.DoesNotExist:
            return _result("not_found", detail="Unknown action link.")

        if action_row.used_at is not None:
            return _result(
                "already_used",
                action=action_row.action,
                detail="This action link has already been used.",
            )

        if now >= action_row.expires_at:
            return _result(
                "expired",
                action=action_row.action,
                detail="This action link has expired.",
            )

        reminder: Reminder = action_row.reminder
        block: Block = reminder.block

        if block.completed_at is not None:
            # Stamp the token used so a stale link can't be replayed
            # later, but report the no-op so the view can render
            # something honest.
            with transaction.atomic():
                action_row.mark_used(now=now)
            return _result(
                "block_completed",
                action=action_row.action,
                block_uuid=str(block.uuid),
                page_slug=block.page.slug if block.page_id else None,
                detail="That block is already complete.",
            )

        with transaction.atomic():
            self._apply_action(action_row.action, block, reminder, now)
            action_row.mark_used(now=now)

        return _result(
            "executed",
            action=action_row.action,
            block_uuid=str(block.uuid),
            page_slug=block.page.slug if block.page_id else None,
            detail=_executed_detail(action_row.action),
        )

    def _apply_action(
        self,
        action: str,
        block: Block,
        reminder: Reminder,
        now,
    ) -> None:
        if action == ReminderAction.ACTION_COMPLETE:
            self._set_block_type(block, "done")
            return

        if action == ReminderAction.ACTION_MARK_DOING:
            # The block-completed guard upstream already short-circuited
            # done/wontdo, so a "mark doing" click here can safely flip
            # the block to the doing state regardless of its prior type
            # (todo, bullet, later, etc.). SetBlockTypeCommand no-ops if
            # it's already doing.
            self._set_block_type(block, "doing")
            return

        if action == ReminderAction.ACTION_MOVE_TO_TODAY:
            self._move_block_to_today(block)
            return

        delta = _SNOOZE_DELTAS.get(action)
        if delta is None:
            # Choices are constrained at the model layer, so we'd only
            # land here on a schema/data drift. Surface it loudly.
            raise ValueError(f"unsupported reminder action: {action}")

        self._snooze_reminder(reminder, delta, now)

    @staticmethod
    def _set_block_type(block: Block, block_type: str) -> None:
        # Routing through SetBlockTypeCommand keeps the transition
        # behavior consistent with toggle-todo / chat tools — including
        # the content-prefix swap and the side-effect that flips any
        # pending reminders to skipped on entering a terminal state.
        set_form = SetBlockTypeForm(
            {
                "user": block.user_id,
                "block": str(block.uuid),
                "block_type": block_type,
            }
        )
        if not set_form.is_valid():
            raise AssertionError(f"SetBlockTypeForm invalid: {set_form.errors}")
        SetBlockTypeCommand(set_form).execute()

    @staticmethod
    def _move_block_to_today(block: Block) -> None:
        # Routing through MoveBlockToDailyCommand keeps the move
        # consistent with the in-app "move to daily" flow — descendants
        # come along, the block lands at the bottom of the target page,
        # and both pages get their modified_at bumped. `target_date` is
        # omitted so the command resolves "today" in the user's
        # timezone at click time. Already on today's daily → graceful
        # no-op inside the command. The reminder is left alone: moving
        # a block is neither completing nor deferring it.
        move_form = MoveBlockToDailyForm(
            {
                "user": block.user_id,
                "block": str(block.uuid),
            }
        )
        if not move_form.is_valid():
            raise AssertionError(f"MoveBlockToDailyForm invalid: {move_form.errors}")
        MoveBlockToDailyCommand(move_form).execute()
        # The move command works on its own instance of the block, so
        # refresh ours — the caller reads `block.page.slug` to build the
        # confirmation page's "Open block" link, which should now point
        # at the daily note the block landed on.
        block.refresh_from_db()

    @staticmethod
    def _snooze_reminder(reminder: Reminder, delta: timedelta, now) -> None:
        # Reuse this Reminder row instead of spawning a new one. Resetting
        # status + sent_at brings it back into the pending-reminder world,
        # which means `Block.get_pending_reminder()` (used by the popover
        # and snooze tools) will surface it again.
        reminder.fire_at = now + delta
        reminder.sent_at = None
        reminder.status = Reminder.STATUS_PENDING
        reminder.last_error = ""
        reminder.save(
            update_fields=[
                "fire_at",
                "sent_at",
                "status",
                "last_error",
                "modified_at",
            ]
        )


_SNOOZE_DELTAS = {
    ReminderAction.ACTION_SNOOZE_15M: timedelta(minutes=15),
    ReminderAction.ACTION_SNOOZE_30M: timedelta(minutes=30),
    ReminderAction.ACTION_SNOOZE_1H: timedelta(hours=1),
    ReminderAction.ACTION_SNOOZE_1D: timedelta(days=1),
}


def _executed_detail(action: str) -> str:
    if action == ReminderAction.ACTION_COMPLETE:
        return "Marked the block as done."
    if action == ReminderAction.ACTION_MARK_DOING:
        return "Marked the block as doing."
    if action == ReminderAction.ACTION_MOVE_TO_TODAY:
        return "Moved the block to today's daily note."
    if action == ReminderAction.ACTION_SNOOZE_15M:
        return "Snoozed for 15 minutes."
    if action == ReminderAction.ACTION_SNOOZE_30M:
        return "Snoozed for 30 minutes."
    if action == ReminderAction.ACTION_SNOOZE_1H:
        return "Snoozed for 1 hour."
    if action == ReminderAction.ACTION_SNOOZE_1D:
        return "Snoozed for 1 day."
    return "Action applied."


def _result(
    status: str,
    *,
    action: Optional[str] = None,
    block_uuid: Optional[str] = None,
    page_slug: Optional[str] = None,
    detail: str = "",
) -> ConsumeReminderActionData:
    return {
        "status": status,
        "action": action,
        "block_uuid": block_uuid,
        "page_slug": page_slug,
        "detail": detail,
    }
