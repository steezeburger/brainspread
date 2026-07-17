FROM python:3.13-slim as base
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT="/usr/local"

# install uv and compilation dependencies
# https://cryptography.io/en/latest/installation/
# postgresql-client provides pg_dump for the scheduler's nightly backup
# job (bookworm ships client 15, matching the postgres:15.4 db image)
RUN apt-get update && apt-get install -y build-essential libssl-dev libffi-dev python3-dev cargo curl postgresql-client
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# supercronic runs the repo crontab in the scheduler service
# (see crontab and bin/run-scheduler.sh)
ARG TARGETARCH
RUN curl -fsSL -o /usr/local/bin/supercronic \
    "https://github.com/aptible/supercronic/releases/download/v0.2.33/supercronic-linux-${TARGETARCH:-amd64}" \
  && chmod +x /usr/local/bin/supercronic

# install python dependencies
RUN mkdir /code
WORKDIR /code
COPY pyproject.toml /code
COPY uv.lock /code
RUN uv sync --frozen

# install application into container
COPY . /code

# run application
EXPOSE 8000

WORKDIR /code/app

# this CMD is overridden by the command in docker-compose.yml for local development
CMD /code/bin/wait-for-it.sh db:${POSTGRES_PORT:-5432} -- python /code/app/manage.py runserver 0.0.0.0:${WEB_PORT:-8000}
