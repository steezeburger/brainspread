# Project Setup

**The canonical setup is all-Docker (workflow A below).** That's what the
`just …` recipes target, what CI runs, and what every contributor and
reviewer is expected to use day-to-day. If you're a human setting this
up locally, stop reading after workflow A.

Workflows B and C exist as fallbacks for environments that can't run a
full Docker stack — most often a coding agent (Claude Code on web) that
has no Docker daemon, or the rare case where a contributor wants to
attach a native debugger to the Django process without dockerizing the
whole thing. Don't reach for them as a daily-dev preference; they
sidestep `just`, drift from CI, and the maintenance burden lives on
whoever picked them.

| Workflow                       | Postgres   | Django / pytest | When to use                                                                          |
| ------------------------------ | ---------- | --------------- | ------------------------------------------------------------------------------------ |
| **A. All-Docker (canonical)**  | Docker     | Docker          | Default for humans and CI. Use this unless you literally can't.                      |
| **B. Hybrid fallback**         | Docker     | Host (uv)       | Coding agents that can't `docker compose run web` but can run `docker compose up db`, or one-off native-debugger sessions. |
| **C. Fully-local fallback**    | Host (apt) | Host (uv)       | Environments with no Docker daemon at all (Claude Code on web, restricted CI).       |

Workflows B and C share the same Django side; they differ only in where
Postgres comes from. All three read configuration from the same `.env`
file, so the common bootstrap steps below apply to everything.

---

## Common: bootstrap the repo (all workflows)

```bash
cd packages/django-app

# 1. Create the env file from the template.
just copy-env                                 # or: cp .env.template .env

# 2. Generate a Django secret key and paste it into .env.
just generate-secret-key                      # workflow A only — see below for B/C
# Manually update DJANGO_SECRET_KEY in .env with the printed value.
```

If you don't have `just` (workflow C), generate the secret key with:

```bash
uv run python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

`.env.template` defaults to `POSTGRES_PORT=5433` so the dockerized
Postgres doesn't fight a host-side install. If you go fully local
(workflow C) and run system Postgres on its default 5432, change
`POSTGRES_PORT` to `5432`.

---

## Workflow A — All-Docker (default)

Everything runs in containers. This is the path the `just` recipes and
CI assume.

```bash
just create-volumes
just build
just up-d db
just migrate
just reload-db                                # loads dev_data.json
just up
```

Key commands:

| Command                    | What it does                                  |
| -------------------------- | --------------------------------------------- |
| `just up` / `just down`    | Start / stop all services                     |
| `just up-d`                | Start in background                           |
| `just migrate`             | Run database migrations                       |
| `just makemigrations`      | Create new migrations                         |
| `just test`                | Run pytest in the web container               |
| `just shell`               | Django shell                                  |
| `just reload-db`           | Reset the DB and reload `dev_data.json`       |
| `just tail-logs web 100`   | Tail the web service logs                     |
| `just prepush`             | Format + lint + Django check + tests          |

Access:

- Web app: `http://localhost:8001/`
- Admin: `http://localhost:8001/admin/`
- Default credentials: `admin@email.com` / `password`

---

## Common bootstrap for workflows B and C (host-side Django)

Both non-Docker workflows assume `.env` exists with a real
`DJANGO_SECRET_KEY` (see the common bootstrap section above). Then:

```bash
cd packages/django-app

# Sync the Python deps from uv.lock into .venv. --frozen keeps the lock
# authoritative so you don't drift from CI.
uv sync --frozen
```

The Django app reads its config from environment variables. `uv run`
inherits the shell env, but **does not auto-load `.env`** the way
docker-compose does. Either use direnv, or:

```bash
set -a; source .env; set +a
```

The minimum exported set:

```bash
export DJANGO_SECRET_KEY=...                 # any non-empty value for dev
export DEBUG=true
export ALLOWED_HOSTS=localhost,127.0.0.1
export POSTGRES_DB=brainspread
export POSTGRES_USER=brainspread
export POSTGRES_PASSWORD=brainspread
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=5433                    # 5432 if you went fully local
```

---

## Workflow B — Docker for Postgres + uv for Django (fallback)

Same Postgres 15.4 image CI uses, but the web process runs straight
from your venv. Use this only when workflow A isn't available — most
often for an agent or one-off IDE-debugger sessions.

```bash
# Start *only* the db service from docker-compose.
just up-d db

# Apply migrations and seed dev data — runs against the dockerized
# Postgres on POSTGRES_PORT (default 5433 from .env.template).
uv run app/manage.py migrate
uv run app/manage.py loaddata dev_data.json

# Run the dev server.
uv run app/manage.py runserver 0.0.0.0:${WEB_PORT:-8000}

# Run the tests. Django's runner and pytest both work; both pick up
# DJANGO_SETTINGS_MODULE from pyproject.toml's [tool.pytest.ini_options].
uv run app/manage.py test
# or:
uv run pytest --reuse-db
```

---

## Workflow C — fully local, no Docker at all (fallback)

Last-resort path for environments with no Docker daemon. Postgres
lives on the host; the Django side is identical to workflow B.

### Install + start Postgres

Linux (Debian/Ubuntu):

```bash
sudo apt-get install -y postgresql
sudo pg_ctlcluster 16 main start            # version may differ
```

macOS:

```bash
brew install postgresql@15
brew services start postgresql@15
```

### Create the dev database

```bash
sudo -u postgres psql -c "CREATE USER brainspread WITH PASSWORD 'brainspread' SUPERUSER;"
sudo -u postgres psql -c "CREATE DATABASE brainspread OWNER brainspread;"
```

`POSTGRES_PORT=5432` for this workflow (the system Postgres default).
Update your env accordingly.

### Run Django + tests

Same as workflow B from here:

```bash
uv run app/manage.py migrate
uv run app/manage.py loaddata dev_data.json
uv run app/manage.py runserver
uv run app/manage.py test
```

---

## Caveats and gotchas (workflows B and C)

- **`just` recipes assume Docker.** `just test`, `just migrate`,
  `just shell`, `just prepush`, etc. all `docker compose run` under
  the hood, so they won't work in workflows B/C — call
  `uv run app/manage.py …` directly instead.
- **Non-Docker `prepush` equivalent.** Run these manually before
  pushing if you can't use `just prepush`:
  ```bash
  uv run black app/
  uv run ruff check app/ --fix
  uv run app/manage.py check --deploy
  uv run pytest --reuse-db --no-cov
  ```
- **Postgres major version differs between B and C.** Workflow B is
  pinned to Postgres 15.4 via the Docker image; workflow C uses
  whatever the host package manager ships (often 16+). Migrations
  work across both, but if you hit a version-specific feature, check
  the Docker image first.
- **Threading-aware tests use `TransactionTestCase`.** The chat-reload
  feature (#118) spawns a worker thread, and threaded code can't see
  data inside `TestCase`'s wrapping transaction. Either runner picks
  these up; just be aware they're slower than a pure `TestCase`.
