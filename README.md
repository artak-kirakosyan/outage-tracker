# outage-notifier — Phase 0.5

Nationwide utility outage tracking & notification system for Armenia
(ENA, Veolia, Gazprom-reserved). This is **Phase 0.5 only**: raw
ingestion, nothing else. No users, no addresses, no matching, no
notifications, no parsing of raw content into structured outages — see
`docs/phase-0.5-plan.md` for the full plan and why the scope is this
narrow on purpose.

## Stack

- Python 3.14, [uv](https://docs.astral.sh/uv/) for dependency management
- Django 5.2 — used as an ORM + admin + migrations toolkit, **not** as a
  web app. There are no views/templates beyond `/admin/`.
- SQLite for now, swappable to Postgres later via `outage_notifier/settings/base.py`'s
  `DATABASES` dict — nothing else in the codebase talks to the DB except
  through the ORM, by design.
- Docker Compose for local deployment.

## What's implemented

- `ingestion.RawContent` — the entire Phase 0.5 schema. One row per
  fetch attempt (success or failure), tagged by `provider` and
  `source_type`.
- Three fetchers, one per source:
  - `ENAFetcher` — `https://www.ena.am/Info.aspx?id=5&lang=1`
  - `VeoliaWebFetcher` — `interactive.vjur.am`, 3 paginated pages
  - `VeoliaTelegramFetcher` — `https://t.me/s/VeoliaJur` (public preview
    page, no bot-admin/userbot session needed — see plan doc)
- Three management commands (`fetch_ena`, `fetch_veolia_web`,
  `fetch_veolia_telegram`) that each run their fetcher and persist
  results.
- `run_scheduler` — a management command that runs all three fetchers
  forever, each on its own configurable interval, as the container's
  long-running process. One thread per provider; a failure in one never
  stops the others.
- Every successful fetch is also mirrored to a plain file under
  `RAW_DUMP_DIRECTORY/<provider>/`, for convenient manual eyeballing —
  same pattern as the old repo's `DUMP_DIRECTORY`.
- Django admin, registered for `RawContent`, for browsing what's been
  collected without writing SQL.

## ⚠️ Known limitation of this build environment

This project was scaffolded and tested inside a sandboxed dev
environment whose network egress is limited to package registries
(PyPI, GitHub, npm) — it **cannot reach `ena.am`, `vjur.am`, or `t.me`**.
Everything that doesn't require hitting those live sites has been
verified for real: dependency resolution, Django migrations, the full
fetch → store → dump pipeline, and partial-failure handling — all
covered by the test suite below, which mocks HTTP responses instead of
hitting the network.

**You'll need to do the first live smoke test yourself**, on a machine
that can reach those three domains:

```bash
uv run manage.py fetch_ena
uv run manage.py fetch_veolia_web
uv run manage.py fetch_veolia_telegram
```

If any of them error, it's most likely a changed URL, a User-Agent
block, or an SSL/TLS quirk — check `.dumps/` and the `RawContent.error_message`
field for details.

## Local setup (without Docker)

```bash
uv sync
cp .env.example .env          # adjust if needed; defaults are fine for local
uv run manage.py migrate
uv run manage.py fetch_ena              # smoke test — see limitation above
uv run manage.py fetch_veolia_web
uv run manage.py fetch_veolia_telegram
uv run manage.py createsuperuser        # optional, for /admin/
uv run manage.py runserver              # optional, for /admin/
```

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

This starts:
- `scheduler` — the long-running process, fetching all three sources on
  their configured intervals (see `.env.example`)
- `admin` — optional Django admin at `http://localhost:8000/admin/`
  (run `docker compose run admin manage.py createsuperuser` once first)

Both share a named volume (`db-data`) so the SQLite file and dumped
files persist across restarts and are visible to both containers.

## Running tests

```bash
uv run --group dev pytest -v
```

All fetcher/storage/scheduler tests run against mocked HTTP (via the
`responses` library) and an in-memory SQLite DB — no network access
required, and none of the live provider sites are touched by the test
suite.

## Project layout

```
outage_notifier/        # Django project (settings, urls, wsgi/asgi)
  settings/
    base.py              # shared settings — start here
    local.py             # dev overrides
    test.py              # in-memory DB, tmp dump dir
ingestion/               # the only Django app in Phase 0.5
  models.py               # Provider, SourceType, FetchStatus, RawContent
  admin.py
  storage.py               # save_raw_content(): DB row + file dump
  scheduler.py              # thread-per-job scheduler primitive
  fetchers/
    base.py                  # BaseFetcher / FetchTarget
    http.py                   # fetch_page_text() — the only place requests.get lives
    ena.py
    veolia_web.py
    veolia_telegram.py
    runner.py                  # run_fetcher(): fetch all targets, save every result
  management/commands/
    fetch_ena.py
    fetch_veolia_web.py
    fetch_veolia_telegram.py
    run_scheduler.py
  tests/
docs/
  phase-0.5-plan.md      # detailed plan + Phase 1 prep notes
scripts/
  docker-entrypoint.sh
```

Deliberately **not** built yet, but anticipated in this layout so later
phases don't require reshuffling: `bot/` (Telegram CRUD bot), a
`processing/` app (raw → structured `OutageEvent`), `matching/`
(address ↔ outage), `notifications/` (send + log). See
`docs/phase-0.5-plan.md` §6 for what each of those will need.
