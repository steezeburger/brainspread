FROM python:3.13-slim as base
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT="/usr/local"

# install uv and compilation dependencies
# https://cryptography.io/en/latest/installation/
RUN apt-get update && apt-get install -y build-essential libssl-dev libffi-dev python3-dev cargo
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

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
