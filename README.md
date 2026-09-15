# outage-notifier

Nationwide utility outage tracking & notification system for Armenia
(ENA, Veolia, Gazprom-reserved).

- **Phase 0.5 (done):** raw ingestion — fetch ENA/Veolia, store every
  fetch verbatim. No parsing, no users, no matching, no notifications.
  See `docs/phase-0.5-plan.md`.
- **Phase 1, raw→structured parsing (done):** parses `RawContent` rows
  (ENA's planned-outage prose, Veolia's Telegram posts) into structured
  announcements/locations. See `docs/phase-1-processing-plan.md`.
- **Phase 1, structured storage (done):** `OutageAnnouncement`/
  `OutageLocation` models, the `process_raw_content` command that ties
  the parsers to `RawContent` (including an HTML-extraction step the
  parsers need but didn't have — see the plan doc §9), and the
  scheduler job that runs it.
- **Phase 1.3, users, matching & notifications (done):**
  `Region`/`Channel` enums, `accounts.User`/`accounts.Address` models,
  the `matching` layer, `notifications.NotificationLog` + delivery, and
  the Telegram bot (registration, address CRUD, notification history)
  are all in place. See
  `docs/phase-1.3-users-matching-notifications-plan.md`.

Phase 1 is complete. Not yet started: Phase 2 (Gazprom) and Phase 3
(paywall/entitlements) — see `docs/project-plan.md` §6.

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
- `processing` — parses and persists structured outage data (see
  `docs/phase-1-processing-plan.md`):
  - `html_extract.py` — pulls the section/posts each parser below
    expects out of the full page HTML `RawContent.content` actually
    stores (§9 — a gap the original parsing-only slice didn't cover).
  - `parsers.veolia_telegram` — full structured parse of a Telegram
    post: marz/district, time window, and each address decomposed into
    street/range/parity (`address_grammar.py`).
  - `parsers.ena_planned` — shallow parse of ENA's planned-outage
    prose: date/region/time window structured, address text kept
    verbatim (deliberately not decomposed — see the plan doc §4).
  - `models.py` — `OutageAnnouncement`/`OutageLocation`.
  - `process_raw_content` management command — ties the above together
    against `RawContent.processed`, idempotent across overlapping
    fetches (§6), also run by `run_scheduler`.
- `accounts` — `User` (channel-generic identity, not Telegram-specific)
  and `Address` (no provider field; `region` is enum-backed via
  `common.enums.Region`, other place fields are free text) — see
  `docs/phase-1.3-users-matching-notifications-plan.md`. CRUD via the
  Telegram bot (`bot/`, below); no CRUD in Django admin beyond viewing.
- `matching` — pure functions, no models: `find_matches_for_address()`
  matches an `Address` against `OutageAnnouncement`s two ways —
  structured (Veolia's `OutageLocation` rows: street + house-number
  range/parity, `confidence="high"`) and raw-text substring (ENA's
  planned block: street-name only, no house-number check,
  `confidence="low"` — an intentional, documented over-match). Failed
  ENA parses are excluded (their `raw_address_text` is an unparsed
  block, not a real address list). `check_match` management command —
  manually test one address against one announcement (see "Testing a
  specific match" below).
- `notifications` — `NotificationLog` model +
  `compute_pending_notifications()`, which logs every new match with
  `status="pending"` and is idempotent (`get_or_create` on
  `(address, outage_announcement)`); run by `run_scheduler` and
  manually via `compute_notifications`. `notifications/send.py`
  delivers `PENDING` rows via the Telegram Bot API
  (`send_pending_notifications()`, batch; also run by
  `run_scheduler` and manually via `send_notifications`) and marks
  each `sent`/`failed`. A `failed` row isn't retried automatically.
- `bot` — the Telegram bot (`python-telegram-bot` v20+, polling):
  `/start` registers a `User`; menu-driven, inline-keyboard address
  CRUD (add/edit/delete — no address id ever typed by the user);
  `/notifications` for recent history. `run_bot` management command;
  runs as its own `docker-compose` service, separate from `scheduler`.

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
uv run manage.py run_bot                # starts the Telegram bot (needs TELEGRAM_BOT_TOKEN in .env)
```

## Testing a specific match

To confirm an address actually catches a specific outage (and see the
exact notification text) without waiting for real data or the
scheduler's time-bounded scan:

```bash
uv run manage.py check_match --address <address_id> --announcement <announcement_id>
```

Reports the geography check, the text/location match result, and — if
matched — previews the notification. Add `--send` to also log and
actually deliver it via Telegram:

```bash
uv run manage.py check_match --address <address_id> --announcement <announcement_id> --send
```

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

This starts:
- `scheduler` — the long-running process, fetching all three sources on
  their configured intervals, plus `process_raw_content` and the
  compute+send notifications job (see `.env.example`)
- `bot` — the Telegram bot (polling), separate from `scheduler` so a
  bot restart doesn't interrupt fetching. Needs `TELEGRAM_BOT_TOKEN` set.
- `admin` — optional Django admin at `http://localhost:8000/admin/`
  (run `docker compose run admin manage.py createsuperuser` once first)

All three share a named volume (`db-data`) so the SQLite file and
dumped files persist across restarts and are visible to every container.

## Running tests

```bash
uv run --group dev pytest -v
```

All fetcher/storage/scheduler tests run against mocked HTTP (via the
`responses` library) and an in-memory SQLite DB — no network access
required, and none of the live provider sites are touched by the test
suite. `processing`'s parser tests run against real fixture data pulled
from actual fetched content (see `processing/tests/fixtures/`), not
synthetic examples.

## Project layout

```
common/                 # cross-app code with no models of its own
  enums.py               # Provider, Region, Channel — shared across apps
outage_notifier/        # Django project (settings, urls, wsgi/asgi)
  settings/
    base.py              # shared settings — start here
    local.py             # dev overrides
    test.py              # in-memory DB, tmp dump dir
ingestion/               # raw fetch -> RawContent (Phase 0.5)
  models.py               # SourceType, FetchStatus, RawContent (Provider now in common.enums)
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
processing/              # RawContent -> structured data (Phase 1)
  normalize.py             # nbsp/dash/whitespace normalization
  armenian_dates.py         # month-name -> number lookup, shared
  address_grammar.py         # Veolia's comma-list grammar (street/range/parity)
  html_extract.py             # splits/extracts what each parser below expects
                                # out of the full page HTML RawContent stores
  parsers/
    veolia_telegram.py         # full structured parse
    ena_planned.py              # shallow parse — see plan doc §4 for why
  idempotency.py               # external_ref computation (ENA hash; Veolia
                                # uses the real data-post id directly)
  models.py                     # OutageAnnouncement, OutageLocation
  admin.py
  migrations/
  management/commands/
    process_raw_content.py        # ties RawContent -> the models above
  tests/
accounts/                # Address/User models (Phase 1.3)
  models.py               # User (channel-generic identity), Address (no provider field)
  admin.py
  migrations/
  tests/
matching/                # Address <-> OutageAnnouncement matching (Phase 1.3)
  geography.py             # OutageAnnouncement.marz -> Region canonicalization
  matcher.py                # find_matches_for_address(); match_confidence_for_announcement()
                              # is the pure per-pair check it's built on, also used by check_match
  management/commands/
    check_match.py             # manually test one address against one announcement
  tests/
notifications/            # Match -> logged NotificationLog -> delivered (Phase 1.3)
  models.py                 # NotificationLog (pending/sent/failed)
  compute.py                  # compute_pending_notifications() -- match + log
  send.py                      # send_pending_notifications() / send_notification() -- deliver via Telegram
  admin.py
  migrations/
  management/commands/
    compute_notifications.py
    send_notifications.py
  tests/
bot/                      # Telegram bot: registration, address CRUD, notification history (Phase 1.3)
  handlers.py               # PTB conversation handlers (inline-keyboard menus, no typed address ids)
  services.py                 # sync DB operations behind the handlers (Django ORM is sync-only)
  management/commands/
    run_bot.py                  # starts the bot (polling)
  tests/
docs/
  phase-0.5-plan.md      # detailed plan + Phase 1 prep notes
  phase-1-processing-plan.md  # scope, schema design, decisions, test results
  phase-1.3-users-matching-notifications-plan.md  # this slice's design + locked decisions
scripts/
  docker-entrypoint.sh
```
