from typing import Any, Dict, List

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.list_automations_form import ListAutomationsForm
from ..repositories import AutomationRunRepository, BlockRepository
from ..services.automation_spec import AutomationSpecError, parse_automation_block


class ListAutomationsCommand(AbstractBaseCommand):
    """Summarize the user's ``#automation`` definitions (issue #143).

    Backs the ``list_automations`` LLM tool and (later) the settings UI.
    Malformed definitions are included with their ``parse_error`` rather
    than hidden — surfacing broken specs is half the point of listing.
    """

    def __init__(self, form: ListAutomationsForm) -> None:
        self.form = form

    def execute(self) -> List[Dict[str, Any]]:
        super().execute()

        user = self.form.cleaned_data["user"]
        summaries: List[Dict[str, Any]] = []
        for block in BlockRepository.get_automation_blocks(user):
            summary: Dict[str, Any] = {"block_uuid": str(block.uuid)}
            try:
                spec = parse_automation_block(block)
            except AutomationSpecError as exc:
                summary.update(
                    {
                        "name": block.first_content_line() or "Automation",
                        "slug": None,
                        "enabled": None,
                        "trigger": None,
                        "action": None,
                        "parse_error": str(exc),
                    }
                )
            else:
                summary.update(
                    {
                        "name": spec.name,
                        "slug": spec.slug,
                        "enabled": spec.enabled,
                        "trigger": spec.trigger.kind,
                        "trigger_detail": (
                            spec.trigger.schedule.raw if spec.trigger.schedule else ""
                        ),
                        "action": spec.action.raw,
                        "parse_error": None,
                    }
                )

            latest = AutomationRunRepository.latest_for_automation(str(block.uuid))
            summary["last_run"] = latest.to_dict() if latest else None
            summaries.append(summary)
        return summaries
