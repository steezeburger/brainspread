import logging
from typing import Optional

from django.db import transaction
from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.run_automation_form import RunAutomationForm
from ..models import AutomationRun, AutomationRunData, Block
from ..repositories import AutomationRunRepository
from ..services import automation_actions, query_engine
from ..services.automation_spec import (
    QUERY_VIEW,
    AutomationSpecError,
    parse_automation_block,
)
from ..services.view_execution import resolve_and_run_view, run_filter

logger = logging.getLogger(__name__)

# Cap how many blocks a single run will act on, so a too-broad query can't
# fan a single automation out across the user's whole graph. Runs that hit
# the cap report ``truncated: true`` in their result.
MAX_ACTION_BLOCKS = 500


class RunAutomationCommand(AbstractBaseCommand):
    """Execute one ``#automation`` block, recording the outcome on an
    AutomationRun (issue #143).

    Shared by every trigger surface — the manual "run now" endpoint and
    the schedule poller both go through here. Resolves the spec's
    ``query:: view:<slug>`` to a block set and runs the declarative
    ``command`` action over it, honoring the ``allow::`` capability list.
    ALL failures — spec errors, missing views, and unexpected exceptions —
    are captured on the run rather than raised, so a bad automation never
    crashes a batch the poller is iterating and a run can never be left
    stranded in ``running``.
    """

    def __init__(self, form: RunAutomationForm) -> None:
        self.form = form

    def execute(self) -> AutomationRunData:
        super().execute()

        user = self.form.cleaned_data["user"]
        block = self.form.cleaned_data["automation_block"]
        # BaseForm.clean drops keys that weren't submitted, so the field
        # default never survives — resolve the fallback here.
        trigger = self.form.cleaned_data.get("trigger") or AutomationRun.TRIGGER_MANUAL

        # The scheduler pre-claims the run (see RunDueAutomationsCommand's
        # claim-then-execute) so no definition locks are held during
        # execution; manual/tool paths create it here.
        run = self.form.cleaned_data.get("run")
        if run is None:
            run = AutomationRunRepository.create(
                user=user,
                automation_block_uuid=str(block.uuid),
                trigger=trigger,
                status=AutomationRun.STATUS_RUNNING,
                started_at=timezone.now(),
            )

        try:
            return self._run_spec(run, user, block)
        except Exception as exc:  # noqa: BLE001 - never strand a RUNNING row
            logger.exception("automation %s run failed unexpectedly", block.uuid)
            return self._finish(
                run, AutomationRun.STATUS_FAILED, error=f"unexpected error: {exc}"
            )

    def _run_spec(self, run: AutomationRun, user, block: Block) -> AutomationRunData:
        try:
            spec = parse_automation_block(block)
        except AutomationSpecError as exc:
            return self._finish(run, AutomationRun.STATUS_FAILED, error=str(exc))

        if not spec.enabled:
            return self._finish(
                run, AutomationRun.STATUS_SKIPPED, result={"reason": "disabled"}
            )

        try:
            action_def = automation_actions.resolve_action(spec.action.verb)
        except automation_actions.ActionError as exc:
            return self._finish(run, AutomationRun.STATUS_FAILED, error=str(exc))

        if action_def.requires_query and spec.query is None:
            return self._finish(
                run,
                AutomationRun.STATUS_FAILED,
                error=(
                    f"action `{spec.action.verb}` requires a " "`query:: view:<slug>`"
                ),
            )

        blocks: list[Block] = []
        truncated = False
        if spec.query is not None:
            try:
                if spec.query.kind == QUERY_VIEW:
                    view, blocks, truncated = resolve_and_run_view(
                        user,
                        limit=MAX_ACTION_BLOCKS,
                        view_slug=spec.query.view_slug,
                    )
                    if view is None:
                        return self._finish(
                            run,
                            AutomationRun.STATUS_FAILED,
                            error=(f"saved view `{spec.query.view_slug}` not found"),
                        )
                else:
                    blocks, truncated = run_filter(
                        user,
                        spec.query.filter_spec or {},
                        limit=MAX_ACTION_BLOCKS,
                    )
            except query_engine.QueryEngineError as exc:
                return self._finish(
                    run, AutomationRun.STATUS_FAILED, error=f"query error: {exc}"
                )

        # `allow::` omitted = the action line itself is the authorization:
        # grant exactly the declared verb. An explicit list is honored as
        # written (it narrows/extends, and stays mandatory for the future
        # prompt action, where the LLM picks tools at runtime).
        effective_allow = (
            spec.allow if spec.allow is not None else frozenset({action_def.capability})
        )
        ctx = automation_actions.ActionContext(
            user=user, allow=effective_allow, has_query=spec.query is not None
        )

        try:
            with transaction.atomic():
                action_result = automation_actions.run_action(spec.action, ctx, blocks)
        except automation_actions.ActionError as exc:
            return self._finish(run, AutomationRun.STATUS_FAILED, error=str(exc))

        return self._finish(
            run,
            AutomationRun.STATUS_SUCCEEDED,
            result={
                "matched": len(blocks),
                "affected": action_result.affected,
                "action": spec.action.verb,
                "truncated": truncated,
            },
        )

    def _finish(
        self,
        run: AutomationRun,
        status: str,
        result: Optional[dict] = None,
        error: str = "",
    ) -> AutomationRunData:
        run.status = status
        run.finished_at = timezone.now()
        run.result = result or {}
        run.last_error = error
        run.save(
            update_fields=[
                "status",
                "finished_at",
                "result",
                "last_error",
                "modified_at",
            ]
        )
        return run.to_dict()
