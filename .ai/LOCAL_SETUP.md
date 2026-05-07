# Local (non-Docker) Setup

The default workflow runs everything in Docker (see [PROJECT_SETUP.md](./PROJECT_SETUP.md)
and `just up-d` / `just test`). This file documents two alternatives that
keep Django out of a container so:

- **the cloud Claude Code env can run tests and lints** without a Docker
  daemon, and
- **local IDE debugging works against a real interpreter** without
  shelling into a container.

There are three workflows in total — pick the one that matches your
constraints:

| Workflow                      | Postgres   | Django / pytest | When to use                                                                 |
| ----------------------------- | ---------- | --------------- | --------------------------------------------------------------------------- |
| **A. All-Docker (default)**   | Docker     | Docker          | Daily dev, production parity, CI. Just run `just up-d` and `just test`.     |
| **B. Hybrid (recommended)**   | Docker     | Host (uv)       | You want fast Python iteration + native debugger but don't want to install Postgres. |
| **C. Fully local (no Docker)**| Host (apt) | Host (uv)       | You're in an env that can't run Docker (Claude Code on web, restricted CI). |

Workflows B and C share the same Django side; the only difference is
where Postgres comes from.

---

## Common: get the Django side ready (workflows B and C)

Both non-Docker workflows assume you've already done the standard repo
setup (`.env` exists, `DJANGO_SECRET_KEY` is set). If not, follow steps
2–3 of `PROJECT_SETUP.md` first.

```bash
cd packages/django-app

# Sync the Python deps from uv.lock into .venv. --frozen keeps the lock
# authoritative so you don't accidentally drift from CI.
uv sync --frozen
```

The Django app reads its config from environment variables. `uv run`
inherits the shell env, so either `source .env` or use `dotenv` /
`direnv`. The minimum set is:

```bash
export DJANGO_SECRET_KEY=...                 # any non-empty value for dev
export DEBUG=true
export ALLOWED_HOSTS=localhost,127.0.0.1
export POSTGRES_DB=brainspread
export POSTGRES_USER=brainspread
export POSTGRES_PASSWORD=brainspread
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=5433                    # matches .env.template; 5432 if you went fully local
```

---

## Workflow B: Docker for Postgres + uv for Django

This is the recommended local-dev path. You get the same Postgres 15.4
image CI uses, but the web process runs straight from your venv.

```bash
# Start *only* the db service from docker-compose.
just up-d db

# Apply migrations and seed dev data — runs against the dockerized
# Postgres on the host port (POSTGRES_PORT in .env, default 5433).
uv run app/manage.py migrate
uv run app/manage.py loaddata dev_data.json

# Run the dev server.
uv run app/manage.py runserver 0.0.0.0:${WEB_PORT:-8000}

# Run the tests with Django's runner. pytest also works; both pick up
# DJANGO_SETTINGS_MODULE from pyproject.toml's [tool.pytest.ini_options].
uv run app/manage.py test
# or:
uv run pytest --reuse-db
```

`POSTGRES_PORT=5433` matches `.env.template`. If you customized it,
match here too.

---

## Workflow C: fully local (no Docker at all)

Use this when Docker isn't an option. Postgres lives on the host; the
rest is the same as workflow B.

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

`POSTGRES_PORT=5432` in this workflow (the system Postgres default).
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

## Caveats and gotchas

- **Postgres major version**: workflow B pins to Postgres 15.4 via the
  Docker image. Workflow C uses whatever the host's package manager
  ships (often 16+). Migrations work across both, but if you hit a
  version-specific feature, check the docker image first.
- **`just` recipes assume Docker.** `just test`, `just migrate`,
  `just shell` etc. all `docker compose run` under the hood, so they
  won't work in workflows B/C — call `uv run app/manage.py …`
  directly instead.
- **`prepush` runs in Docker.** `just prepush` invokes the dockerized
  test runner. The non-Docker equivalent is:
  ```bash
  uv run black app/
  uv run ruff check app/ --fix
  uv run app/manage.py check --deploy
  uv run pytest --reuse-db --no-cov
  ```
  Run that before pushing if you can't use `just prepush`.
- **Env vars must be exported, not just present in `.env`.** Docker
  Compose reads `.env` automatically; `uv run` does not. Use a
  `.envrc` (direnv) or `set -a; source .env; set +a` to make them
  visible.
- **The chat-reload feature spawns a worker thread (issue #118).**
  Threading-aware tests use `TransactionTestCase` so they get
  committed setup data. Either runner picks them up; just be aware
  they're slower than `TestCase`.
