import os
from typing import Any

from django.core.management.base import BaseCommand

from knowledge.commands import RunDueAutomationsCommand
from knowledge.forms.run_due_automations_form import RunDueAutomationsForm


class Command(BaseCommand):
    """Fire scheduled automations whose slot has arrived (issue #143).

    Run by the `scheduler` docker service on a ~1-minute loop (see
    packages/django-app/docker-compose.yml and bin/run-scheduler.sh),
    alongside send_due_reminders.

    Gated by the AUTOMATIONS_ENABLED env var (defaults to false), same
    opt-in pattern as REMINDERS_ENABLED — unset locally keeps the dev
    scheduler quiet.
    """

    help = "Fire any schedule-triggered automations whose slot has arrived."

    def handle(self, *args: Any, **options: Any) -> None:
        enabled = os.environ.get("AUTOMATIONS_ENABLED", "false").lower() == "true"
        if not enabled:
            self.stdout.write(
                "automations disabled (AUTOMATIONS_ENABLED != 'true'); skipping"
            )
            return

        form = RunDueAutomationsForm({})
        result = RunDueAutomationsCommand(form).execute()

        self.stdout.write(
            self.style.SUCCESS(
                f"automations: considered={result['considered']} "
                f"fired={result['fired']} "
                f"skipped={result['skipped']} "
                f"failed_parse={result['failed_parse']}"
            )
        )
