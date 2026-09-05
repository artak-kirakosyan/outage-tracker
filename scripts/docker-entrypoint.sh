#!/usr/bin/env bash
set -euo pipefail

# Runs on every container start (not baked at build time) so this works
# correctly against a volume-mounted SQLite file, which won't exist yet
# on the very first `docker compose up`.
uv run manage.py migrate --noinput

exec uv run manage.py "$@"
