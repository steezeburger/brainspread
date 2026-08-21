import logging
from typing import List, Tuple, TypedDict

from django.db import transaction
from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.run_automation_form import RunAutomationForm
from ..forms.run_due_automations_form import RunDueAutomationsForm
from ..models import AutomationRun, Block
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
    docker service), in two phases — claim, then execute:

    1. **Claim** (single short transaction): lock the definition blocks
       with SKIP LOCKED, parse, compute due-ness, and insert a RUNNING
       AutomationRun for each due automation. Pure DB work — the locks
       are held for milliseconds, so editing a definition block never
       stalls behind a slow action, and concurrent ticks partition the
       rows instead of double-firing.
    2. **Execute** (no batch locks): run each claimed automation via the
       shared RunAutomationCommand, which finishes the pre-created run
       row. Actions keep their own small transactions; webhook / (future)
       LLM calls happen lock-free.

    The claim row itself is the double-fire guard: due-ness compares the
    cadence's most recent slot against the latest run's ``started_at``
    (see services.automation_schedule), and a claim carries the tick's
    timestamp — so once claimed, a slot can't re-fire even if execution
    is still in flight (or died; a stranded RUNNING claim reads as "ran
    at that slot" and the next slot proceeds normally).

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
        claims: List[Tuple[Block, AutomationRun]] = []

        with transaction.atomic():
            for block in BlockRepository.lock_automation_blocks():
                considered += 1

                try:
                    spec = parse_automation_block(block)
                except AutomationSpecError as exc:
                    if self._is_new_failure(str(block.uuid), str(exc)):
                        claims.append((block, self._claim(block, now)))
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

                claims.append((block, self._claim(block, now)))
                fired += 1

        # Claim transaction committed — definition locks are gone. Execute
        # each claimed run lock-free.
        for block, run in claims:
            self._execute(block, run)

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
    def _claim(block: Block, now) -> AutomationRun:
        """Insert the RUNNING run row that marks this tick's slot as taken.
        ``started_at`` carries the tick's pinned now so due-ness math stays
        deterministic under test."""
        return AutomationRunRepository.create(
            user=block.user,
            automation_block_uuid=str(block.uuid),
            trigger=AutomationRun.TRIGGER_SCHEDULE,
            status=AutomationRun.STATUS_RUNNING,
            started_at=now,
        )

    @staticmethod
    def _execute(block: Block, run: AutomationRun) -> None:
        """Execute one claimed run via the shared command; it records every
        outcome (including parse failures) on the claim row and never
        raises. If the form itself won't validate, finish the claim as
        FAILED rather than stranding it RUNNING."""
        form = RunAutomationForm(
            {
                "user": block.user,
                "automation_block": str(block.uuid),
                "run": str(run.uuid),
                "trigger": AutomationRun.TRIGGER_SCHEDULE,
            }
        )
        if not form.is_valid():
            logger.warning(
                "automation %s dispatch form invalid: %s", block.uuid, form.errors
            )
            run.status = AutomationRun.STATUS_FAILED
            run.finished_at = timezone.now()
            run.last_error = f"dispatch form invalid: {form.errors.as_json()}"
            run.save(
                update_fields=["status", "finished_at", "last_error", "modified_at"]
            )
            return
        RunAutomationCommand(form).execute()
