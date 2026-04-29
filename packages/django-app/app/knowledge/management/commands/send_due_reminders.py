import os
from typing import Any

from django.core.management.base import BaseCommand

from knowledge.commands import SendDueRemindersCommand
from knowledge.forms import SendDueRemindersForm


class Command(BaseCommand):
    """Dispatch reminders whose fire_at has arrived.

    Run by the `scheduler` docker service on a ~1-minute loop (see
    packages/django-app/docker-compose.yml and bin/run-scheduler.sh).

    Gated by the REMINDERS_ENABLED env var so staging PR stacks don't spam
    the user's Discord channel. Set REMINDERS_ENABLED=true in prod .env.
    """

    help = "Dispatch any reminders whose fire_at has arrived."

    def handle(self, *args: Any, **options: Any) -> None:
        enabled = os.environ.get("REMINDERS_ENABLED", "false").lower() == "true"
        if not enabled:
            self.stdout.write(
                "reminders disabled (REMINDERS_ENABLED != 'true'); skipping"
            )
            return

        form = SendDueRemindersForm({})
        result = SendDueRemindersCommand(form).execute()

        self.stdout.write(
            self.style.SUCCESS(
                f"reminders: considered={result['considered']} "
                f"sent={result['sent']} "
                f"skipped={result['skipped']} "
                f"failed={result['failed']}"
            )
        )
