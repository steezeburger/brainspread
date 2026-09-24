import os
from typing import Any

from django.core.management.base import BaseCommand

from knowledge.commands import PurgeExpiredTrashCommand
from knowledge.forms.purge_expired_trash_form import (
    DEFAULT_RETENTION_DAYS,
    PurgeExpiredTrashForm,
)


class Command(BaseCommand):
    """Hard-delete Trash items past the retention window (issue #122).

    Run by the `scheduler` docker service on a ~1-minute loop (see
    packages/django-app/docker-compose.yml and bin/run-scheduler.sh),
    alongside send_due_reminders / run_due_automations.

    Gated by the TRASH_PURGE_ENABLED env var (defaults to false), same
    opt-in pattern as REMINDERS_ENABLED / AUTOMATIONS_ENABLED — unset
    locally keeps the dev scheduler quiet. TRASH_RETENTION_DAYS overrides
    the 30-day default retention window.
    """

    help = "Hard-delete soft-deleted pages/blocks past the retention window."

    def handle(self, *args: Any, **options: Any) -> None:
        enabled = os.environ.get("TRASH_PURGE_ENABLED", "false").lower() == "true"
        if not enabled:
            self.stdout.write(
                "trash purge disabled (TRASH_PURGE_ENABLED != 'true'); skipping"
            )
            return

        retention_days = os.environ.get("TRASH_RETENTION_DAYS", "")
        form_data = {}
        if retention_days:
            form_data["retention_days"] = retention_days

        form = PurgeExpiredTrashForm(form_data)
        if not form.is_valid():
            self.stderr.write(f"invalid TRASH_RETENTION_DAYS: {form.errors}")
            return

        result = PurgeExpiredTrashCommand(form).execute()

        self.stdout.write(
            self.style.SUCCESS(
                f"trash purge: pages_purged={result['pages_purged']} "
                f"blocks_purged={result['blocks_purged']} "
                f"retention_days={retention_days or DEFAULT_RETENTION_DAYS}"
            )
        )
