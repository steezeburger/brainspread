import logging
from typing import Callable, List, Optional

from django.db import transaction
from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.run_automation_form import RunAutomationForm
from ..models import AutomationRun, AutomationRunData, Block
from ..repositories import AutomationRunRepository, BlockRepository
from ..services import automation_actions, query_engine
from ..services.automation_spec import (
    QUERY_VIEW,
    AutomationSpecError,
    parse_automation_block,
)
from ..services.token_context import build_automation_token_context
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

        # `enabled:: false` pauses AMBIENT firing (schedule now; events /
        # webhooks later — this check is their backstop even though the
        # dispatcher also skips disabled specs). An explicit manual run is
        # the strongest intent signal there is and goes through — the UI
        # confirms first when it knows the automation is disabled.
        if not spec.enabled and run.trigger != AutomationRun.TRIGGER_MANUAL:
            return self._finish(
                run, AutomationRun.STATUS_SKIPPED, result={"reason": "disabled"}
            )

        try:
            action_defs = [
                automation_actions.resolve_action(step.verb)
                for step in spec.action.steps
            ]
        except automation_actions.ActionError as exc:
            return self._finish(run, AutomationRun.STATUS_FAILED, error=str(exc))

        # requires_query is the OR over the chain's steps (issue #225): a
        # chain containing even one set verb (or a per-match verb whose
        # args carry {{block.*}} tokens) needs a query::.
        requires_query = any(
            automation_actions.action_requires_query(action_def, step.args)
            for action_def, step in zip(action_defs, spec.action.steps)
        )
        if requires_query and spec.query is None:
            return self._finish(
                run,
                AutomationRun.STATUS_FAILED,
                error=(
                    f"action `{spec.action.raw}` requires a `query::` (either "
                    "one of its verbs always needs a matched-block set, or "
                    "its args use `{{block.*}}` tokens)"
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
        # grant every verb the chain declares. An explicit list is honored
        # as written (it narrows/extends, and stays mandatory for the
        # future prompt action, where the LLM picks tools at runtime).
        effective_allow = (
            spec.allow
            if spec.allow is not None
            else frozenset(action_def.capability for action_def in action_defs)
        )
        # Every step is capability-checked before any step runs, so a
        # chain can't half-execute because a later step wasn't granted.
        for step, action_def in zip(spec.action.steps, action_defs):
            if action_def.capability not in effective_allow:
                return self._finish(
                    run,
                    AutomationRun.STATUS_FAILED,
                    error=(
                        f"action `{step.verb}` is not in the automation's "
                        f"`allow::` list (add `{action_def.capability}`)"
                    ),
                )

        ctx = automation_actions.ActionContext(
            user=user, allow=effective_allow, has_query=spec.query is not None
        )
        # {{count}} is the matched-block total for a query-based run;
        # there's no comparable single number for a for:: run, so it
        # stays unavailable there (bare {{count}} fails loudly).
        token_context = build_automation_token_context(
            user, match_count=len(blocks) if spec.query is not None else None
        )
        for_items = spec.for_spec.items if spec.for_spec is not None else None

        # The matched-block UUID set is fixed once, up front, for the
        # whole chain (issue #225) — a step never re-queries. Between
        # steps the same UUIDs are re-fetched so a later step never reads
        # a stale in-memory copy of content an earlier step rewrote.
        matched_uuids = [str(block.uuid) for block in blocks]
        current_blocks = blocks
        steps_result: List[dict] = []
        pending_sends: List[Callable[[], None]] = []
        total_affected = 0
        all_groups: List[dict] = []
        all_skipped: List[dict] = []

        try:
            with transaction.atomic():
                for index, (step, action_def) in enumerate(
                    zip(spec.action.steps, action_defs)
                ):
                    if index > 0 and spec.query is not None:
                        current_blocks = BlockRepository.get_by_uuids(
                            matched_uuids, user=user
                        )
                    step_result = automation_actions.run_action(
                        step,
                        ctx,
                        current_blocks,
                        token_context=token_context,
                        for_items=for_items,
                    )
                    if action_def.external:
                        pending_sends.extend(step_result.deferred)
                    total_affected += step_result.affected
                    all_groups.extend(step_result.groups)
                    all_skipped.extend(step_result.skipped)
                    steps_result.append(
                        {
                            "verb": step.verb,
                            "affected": step_result.affected,
                            "groups": step_result.groups,
                            "skipped": step_result.skipped,
                        }
                    )
        except automation_actions.ActionError as exc:
            return self._finish(run, AutomationRun.STATUS_FAILED, error=str(exc))

        result = {
            "matched": len(blocks),
            "affected": total_affected,
            "action": spec.action.raw,
            "truncated": truncated,
            "groups": all_groups,
            "skipped": all_skipped,
            "steps": steps_result,
        }

        # External steps (notify now, http later) run only after the DB
        # transaction above has committed, in chain order. A delivery
        # failure here marks the run failed but leaves the DB changes —
        # already committed — in place, and skips any sends still queued.
        for send in pending_sends:
            try:
                send()
            except automation_actions.ActionError as exc:
                return self._finish(
                    run, AutomationRun.STATUS_FAILED, error=str(exc), result=result
                )

        return self._finish(run, AutomationRun.STATUS_SUCCEEDED, result=result)

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
