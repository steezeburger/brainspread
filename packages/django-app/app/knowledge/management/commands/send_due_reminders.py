import os
from typing import Any

from django.core.management.base import BaseCommand

from knowledge.commands import SendDueRemindersCommand
from knowledge.forms import SendDueRemindersForm


class Command(BaseCommand):
    """Dispatch reminders whose fire_at has arrived.

    Run by the `scheduler` docker service on a ~1-minute loop (see
    packages/django-app/docker-compose.yml and bin/run-scheduler.sh).

    Gated by the REMINDERS_ENABLED env var (defaults to false). The
    staging deploy and prod set it to true explicitly via their .env;
    leaving it unset locally keeps the dev scheduler quiet. Non-prod
    environments get a `[<env>]` label prepended via the ENVIRONMENT
    env var so pings are distinguishable from prod ones in Discord.
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
