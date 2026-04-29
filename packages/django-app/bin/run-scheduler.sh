#!/bin/sh
# Scheduler loop — runs periodic Django management commands in the background.
#
# Currently just dispatches due reminders every ~60s (see issue #59). As more
# scheduled jobs get added, consider swapping this for supercronic or similar
# so different jobs can have their own cadences.
#
# The command itself is gated by REMINDERS_ENABLED, so leaving it unset is
# safe (it will no-op until you opt in, e.g. on the prod .env).

set -eu

INTERVAL="${SCHEDULER_INTERVAL_SECONDS:-60}"

echo "scheduler: starting (interval=${INTERVAL}s)"

while true; do
  python /code/app/manage.py send_due_reminders || echo "scheduler: command failed, continuing"
  sleep "$INTERVAL"
done
