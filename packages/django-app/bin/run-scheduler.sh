#!/bin/sh
# Scheduler loop — runs periodic Django management commands in the background.
#
# Dispatches due reminders (issue #59), due automations (issue #143), and
# expired-trash purging (issue #122) every ~60s. As more scheduled jobs get
# added, consider swapping this for supercronic or similar so different jobs
# can have their own cadences.
#
# Each command is gated by its own env var (REMINDERS_ENABLED /
# AUTOMATIONS_ENABLED / TRASH_PURGE_ENABLED), so leaving them unset is safe
# — the loop no-ops until you opt in, e.g. on the prod .env.

set -eu

INTERVAL="${SCHEDULER_INTERVAL_SECONDS:-60}"

echo "scheduler: starting (interval=${INTERVAL}s)"

while true; do
  python /code/app/manage.py send_due_reminders || echo "scheduler: send_due_reminders failed, continuing"
  python /code/app/manage.py run_due_automations || echo "scheduler: run_due_automations failed, continuing"
  python /code/app/manage.py purge_expired_trash || echo "scheduler: purge_expired_trash failed, continuing"
  sleep "$INTERVAL"
done
