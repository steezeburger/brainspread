#!/bin/bash
# Nightly database backup — compressed pg_dump with retention pruning.
# Runs inside the scheduler container via supercronic (see ../crontab);
# `just backup` runs it on demand. /code/backups is the compose bind
# mount, so dumps land on the host at packages/django-app/backups/.
set -euo pipefail

location="${BACKUP_LOCATION:-/code/backups}"
retention_days="${BACKUP_RETENTION_DAYS:-14}"

mkdir -p "$location"
dump_path="${location}/$(date +%Y-%m-%d_%H-%M-%S)-brainspread-dump.sql.gz"

export PGPASSWORD="$POSTGRES_PASSWORD"
pg_dump -h "${POSTGRES_HOST:-db}" -p "${POSTGRES_PORT:-5432}" \
  -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$dump_path"

# a dump without pg_dump's trailing marker is truncated — fail loudly
# rather than silently keeping a bad backup
if ! gunzip -c "$dump_path" | tail -5 | grep -q "PostgreSQL database dump complete"; then
  echo "backup: ${dump_path} is missing the pg_dump completion marker" >&2
  exit 1
fi

echo "backup: wrote ${dump_path} ($(du -h "$dump_path" | cut -f1))"

find "$location" -name '*-brainspread-dump.sql.gz' -mtime +"$retention_days" -delete
