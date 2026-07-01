import logging
from typing import TypedDict

from django.db import transaction
from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.run_automation_form import RunAutomationForm
from ..forms.run_due_automations_form import RunDueAutomationsForm
from ..models import AutomationRun
from ..repositories import AutomationRunRepository, BlockRepository
from ..services import automation_schedule
from ..services.automation_spec import (
    TRIGGER_SCHEDULE,
    AutomationSpecError,
    parse_automation_block,
)
from .run_automation_command import RunAutomationCommand

logger = logging.getLogger(__name__)


class RunDueAutomationsData(TypedDict):
    considered: int
    fired: int
    skipped: int
    failed_parse: int


class RunDueAutomationsCommand(AbstractBaseCommand):
    """One scheduler dispatch tick: fire every schedule-triggered
    automation whose slot has arrived (issue #143).

    Runs on the same cron-like loop as reminders (see the `scheduler`
    docker service). Locks the definition blocks with SKIP LOCKED so
    concurrent ticks never double-fire. Due-ness compares the cadence's
    most recent slot (in the owner's timezone) against the automation's
    last run — see services.automation_schedule for the catch-up-once
    semantics.

    Malformed specs record ONE failed AutomationRun (deduped against the
    latest run's error) instead of spamming a failure per tick; fixing
    the block naturally clears the dedupe.
    """

    def __init__(self, form: RunDueAutomationsForm) -> None:
        self.form = form

    def execute(self) -> RunDueAutomationsData:
        super().execute()

        now = self.form.cleaned_data.get("now") or timezone.now()
        considered = 0
        fired = 0
        skipped = 0
        failed_parse = 0

        with transaction.atomic():
            for block in BlockRepository.lock_automation_blocks():
                considered += 1

                try:
                    spec = parse_automation_block(block)
                except AutomationSpecError as exc:
                    if self._is_new_failure(str(block.uuid), str(exc)):
                        self._fire(block)
                        failed_parse += 1
                    else:
                        skipped += 1
                    continue

                if (
                    not spec.enabled
                    or spec.trigger.kind != TRIGGER_SCHEDULE
                    or spec.trigger.schedule is None
                ):
                    skipped += 1
                    continue

                latest = AutomationRunRepository.latest_for_automation(str(block.uuid))
                due = automation_schedule.is_due(
                    spec.trigger.schedule,
                    latest.started_at if latest else None,
                    now,
                    block.user.tz(),
                )
                if not due:
                    skipped += 1
                    continue

                self._fire(block)
                fired += 1

        return {
            "considered": considered,
            "fired": fired,
            "skipped": skipped,
            "failed_parse": failed_parse,
        }

    @staticmethod
    def _is_new_failure(automation_block_uuid: str, error: str) -> bool:
        """True unless the latest run already failed with this exact error
        — the dedupe that keeps a broken spec from writing a failed run
        every tick."""
        latest = AutomationRunRepository.latest_for_automation(automation_block_uuid)
        return not (
            latest is not None
            and latest.status == AutomationRun.STATUS_FAILED
            and latest.last_error == error
        )

    @staticmethod
    def _fire(block) -> None:
        """Run one automation via the shared command; it records every
        outcome (including parse failures) on an AutomationRun and never
        raises."""
        form = RunAutomationForm(
            {
                "user": block.user,
                "automation_block": str(block.uuid),
                "trigger": AutomationRun.TRIGGER_SCHEDULE,
            }
        )
        if not form.is_valid():
            logger.warning(
                "automation %s dispatch form invalid: %s", block.uuid, form.errors
            )
            return
        RunAutomationCommand(form).execute()
