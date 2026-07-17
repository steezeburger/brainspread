#!/bin/sh
# Scheduler entrypoint — runs the repo's crontab (/code/crontab) with
# supercronic so job definitions live in git and deploy with the app.
# Replaced the old fixed-interval polling loop (issue #59); per-job
# cadences now come from the crontab file.
#
# The reminders command is gated by REMINDERS_ENABLED, so leaving it
# unset is safe (it will no-op until you opt in, e.g. on the prod .env).

set -eu

exec supercronic /code/crontab
