FROM python:3.14-slim

# uv is a single static binary — copy it in rather than pip-installing it,
# per the project's chosen tooling.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=outage_notifier.settings.local

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .
RUN chmod +x scripts/docker-entrypoint.sh

ENTRYPOINT ["scripts/docker-entrypoint.sh"]
CMD ["run_scheduler"]
