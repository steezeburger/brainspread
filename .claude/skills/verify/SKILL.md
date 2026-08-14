---
name: verify
description: Build, run, and drive this app to verify a change end-to-end in an environment without Docker (Claude Code on web). Covers Postgres bootstrap, dev server, and exercising Discord reminder flows.
---

# Verifying changes in a no-Docker environment

The canonical workflow is all-Docker (`just …`); this recipe is the
workflow-C fallback from `.ai/PROJECT_SETUP.md` for environments with
no Docker daemon, with the gotchas that cost time on a cold start.

## Bootstrap (once per session)

```bash
cd packages/django-app
cp .env.template .env
# .env is sourced by shell — the generated Django secret key can contain
# `)` etc. Use a URL-safe token instead:
SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')
sed -i "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=${SECRET}|; s|^POSTGRES_PORT=.*|POSTGRES_PORT=5432|" .env

sudo pg_ctlcluster 16 main start          # version may differ
# .env.template expects postgres/postgres on db "postgres":
sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'postgres';"

uv sync --frozen
set -a; source .env; set +a               # uv run does NOT auto-load .env
uv run app/manage.py migrate
uv run app/manage.py loaddata dev_data.json
```

## Run and drive

```bash
uv run app/manage.py runserver 0.0.0.0:8001   # background it
# Login: admin@email.com / password
```

- Tests: `uv run pytest app --reuse-db --no-cov -q` from
  `packages/django-app` (bare `pytest` from there can't find the
  project; `pytest app` works).
- Lint/format: `uv run black app/ && uv run ruff check app/ --fix`.

## Discord reminder flows

The reminder pipeline has no UI trigger — drive it via the real cron
entrypoint:

- Point the user's `discord_webhook_url` at a local capture server (a
  tiny `http.server` that logs POST bodies) instead of real Discord.
- `SITE_URL=http://localhost:8001 REMINDERS_ENABLED=true \
  uv run app/manage.py send_due_reminders` — it refuses to run without
  `REMINDERS_ENABLED=true`.
- Action links in the captured embed (`/knowledge/r/<token>/`) are
  public no-auth URLs — `curl` them directly to exercise the consume
  path; replaying a token should give 410, garbage tokens 404.
