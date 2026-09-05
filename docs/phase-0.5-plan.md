# Phase 0.5 — Detailed Implementation Plan & Phase 1 Prep Notes

This document is the detailed companion to the top-level
`utility-outage-notifier-plan.md`. That doc covers the *whole*
rearchitecture at a high level; this one is scoped to Phase 0.5 only —
what's actually built, how it's built, how to verify it, and what to
watch for while it's running so Phase 1 isn't designed blind.

Branch: `phase-0.5/raw-ingestion`.

## 1. Scope (confirmed)

Phase 0.5 = raw ingestion only. Concretely, done means:

- Three fetchers (ENA site, Veolia site, Veolia Telegram preview) each
  run on a schedule and write to one shared `RawContent` table.
- Nothing downstream of that table exists yet: no parsing into
  structured outages, no `Address`/`User` models, no matching, no
  notifications, no bot process. Those are Phase 1.
- Success criterion is **data flowing**, not data being *useful* yet —
  the whole point is to front-load collection so Phase 1's parser is
  designed against real samples instead of guesses (see top-level plan,
  §1).

Explicitly out of scope for this phase, even though they're easy to be
tempted into building early: any address-range parsing logic, any
marz/district filtering, Gazprom (no fetcher, `Provider.GAZPROM` exists
purely as a reserved enum value), and any dedup between Veolia's website
and its Telegram channel (both are stored as fully distinct raw rows —
see §5 below on why that's still true even with change-detection).

## 2. What was built

### 2.1 Schema

One model, `ingestion.RawContent`:

| Field | Purpose |
|---|---|
| `provider` | `ena` / `veolia_web` / `veolia_telegram` / `gazprom` (reserved) |
| `source_type` | `html` or `telegram_text` |
| `reference` | the exact URL fetched |
| `content` | raw response body, verbatim — source of truth |
| `fetched_at` | auto-set on creation |
| `fetch_status` | `ok` or `error` |
| `error_message` | populated on failure |
| `dump_file_path` | relative path to the mirrored on-disk copy, if the dump succeeded |
| `processed` | boolean, defaults `False`, **unused until Phase 1** |

`processed` is included now specifically so Phase 1's parser doesn't
need a migration just to start marking rows as consumed — it can start
querying `RawContent.objects.filter(processed=False)` from day one.

### 2.2 Fetchers

Each fetcher declares a list of `FetchTarget`s (usually one URL, three
for Veolia's paginated site) and a `fetch_one()` that turns a target
into raw text. The runner (`ingestion/fetchers/runner.py`) fetches every
target independently and saves a row per target — **one target failing
never loses the others**. This mattered enough to write a dedicated test
(`test_veolia_web_fetcher_tolerates_partial_failure`) simulating page 2
of 3 returning a 503.

- **ENAFetcher** — single GET to `ena.am`. Whether ENA's emergency
  outages live on this same page or need a separate URL is genuinely
  unknown right now (see §5).
- **VeoliaWebFetcher** — 3 independent GETs (`&page=1/2/3`), one row
  each.
- **VeoliaTelegramFetcher** — single GET to `https://t.me/s/VeoliaJur`,
  the public unauthenticated preview page. No bot-admin, no
  userbot/MTProto session — see top-level plan §3 for why that approach
  was rejected. Only returns recent posts, which is fine; full history
  isn't a product requirement.

### 2.3 Change-detection (added beyond the original high-level plan)

Every fetch that returns content identical to the *last successful*
fetch for that same `(provider, reference)` is **not** written as a new
row — it's counted as `unchanged` in the run summary and skipped
entirely (no DB row, no file dump). This wasn't in the original
high-level plan; it was added during implementation because polling
hourly for several days with no dedup would otherwise fill the table
with near-duplicate HTML, making the manual review step in task 10
tedious for no benefit. The check is a plain content-equality comparison
against the most recent `ok` row — no hashing, no fuzzy matching, since
exact byte-identity is all we need to answer "did anything change."

This only affects the *raw* layer's storage efficiency — it has no
bearing on Phase 1 parsing logic, and it's easy to disable (delete the
`get_latest_content` check in `runner.py`) if you'd rather see every
single fetch attempt for some debugging reason.

### 2.4 Scheduler

`run_scheduler` (a management command) starts one daemon thread per
provider, each looping on its own configurable interval
(`ENA_FETCH_INTERVAL_MINUTES`, etc. — see `.env.example`), sleeping via
`threading.Event.wait()` so it can be interrupted cleanly. An exception
in one job's `run_once()` is caught and logged; it does not kill that
job's thread or affect the other providers' threads. This is the
container's long-running process (see `docker-compose.yml`'s
`scheduler` service).

Deliberately not used: Celery, APScheduler, or any external cron.
Per the top-level plan, "a simple cron-in-container or a sleep loop is
fine for v1" — this is that sleep loop, kept in-process so a single
`docker compose up` is enough.

### 2.5 Storage redundancy

Every successful fetch writes to the DB (source of truth) **and**
mirrors to a file under `RAW_DUMP_DIRECTORY/<provider>/<timestamp>_<id>.html`
if the content changed. The file dump is disposable — if writing it
fails (e.g. disk full), the DB row is still saved and the failure is
just logged, never raised. This mirrors the old repo's `DUMP_DIRECTORY`
pattern, kept because it's genuinely convenient for `grep`-ing through
raw HTML while designing the Phase 1 parser without spinning up a DB
shell.

### 2.6 What was verified vs. what's still pending

This sandbox's network egress doesn't reach `ena.am`, `vjur.am`, or
`t.me` (allowlisted to package registries only), so:

**Verified for real:** dependency resolution via `uv`, Django system
checks, migration generation and application, the full fetch → dedup →
store → dump pipeline, partial-failure handling, the scheduler's
threading behavior (including surviving exceptions), and all three
management commands — all under a 14-test suite that mocks HTTP via
`responses` instead of touching the network. `uv run --group dev pytest -v`
passes clean.

**Not yet verified (needs a machine that can reach the real sites):**
whether the actual ENA/Veolia/Telegram pages parse-free as expected —
i.e., whether `requests.get()` against the real URLs returns 200 with
the content we expect, whether either site blocks the default
User-Agent, and whether Telegram's preview page format matches the
fixture used in tests (which was built from a real fetch of
`t.me/s/VeoliaJur` done via a separate, unrestricted tool earlier in
this project's history — see the fixture file's content — but hasn't
been re-verified against a fresh live fetch through this exact
`VeoliaTelegramFetcher` code path).

**Action item for you:** run the three smoke-test commands from the
README on a machine with normal internet access before trusting this in
production:
```bash
uv run manage.py fetch_ena
uv run manage.py fetch_veolia_web
uv run manage.py fetch_veolia_telegram
```
Then check `RawContent.objects.filter(fetch_status="error")` (or just
`/admin/`) for anything unexpected.

## 3. Task checklist

| # | Task | Status |
|---|---|---|
| 1 | Scaffold project with `uv`, Django settings split (base/local/test) | ✅ done |
| 2 | `Provider`/`SourceType`/`FetchStatus`/`RawContent` models + migration | ✅ done |
| 3 | Shared `fetch_page_text()` HTTP helper | ✅ done |
| 4 | `ENAFetcher` | ✅ done, ⚠️ live fetch unverified (see §2.6) |
| 5 | `VeoliaWebFetcher` | ✅ done, ⚠️ live fetch unverified |
| 6 | `VeoliaTelegramFetcher` (handle: `VeoliaJur`) | ✅ done, ⚠️ live fetch unverified |
| 7 | Management commands per fetcher + `run_scheduler` | ✅ done |
| 8 | Logging (stdout, structured summaries) | ✅ done |
| 9 | Docker Compose (`scheduler` + optional `admin`), shared volume | ✅ done, ⚠️ not run through `docker compose up` in this sandbox — Docker isn't available here either; please build/run it yourself and report back if anything's off |
| 10 | Let it run for several days; manually review collected data | ⏳ **this is on you** — nothing here can do a multi-day soak test |

## 4. How to run it

See `README.md` for full setup instructions (local + Docker). Short version:

```bash
uv sync
cp .env.example .env
uv run manage.py migrate
uv run manage.py fetch_ena && uv run manage.py fetch_veolia_web && uv run manage.py fetch_veolia_telegram
uv run manage.py createsuperuser   # optional
uv run manage.py runserver          # optional, browse RawContent at /admin/
```

Or, for the real long-running setup:

```bash
docker compose up --build
```

## 5. Notes to prepare for Phase 1

These are things to actively watch for **while Phase 0.5 is collecting
data**, so that when Phase 1 parsing design starts, you're not staring
at a blank slate. Consider skimming `.dumps/` or `/admin/` every day or
two, not just once at the end of the soak-test window.

- **Address-range format variety.** The top-level plan already
  documents the known rule (main number decides range membership,
  sub-number only matters in explicit comma-separated lists), but the
  actual *textual* patterns ENA and Veolia use to express "1–15",
  "20–40, even only", and "whole street, no numbers" are still unknown.
  As you review dumps, it's worth keeping a running scratch note (a
  text file, a spreadsheet, whatever) of every distinct phrasing you
  spot — Armenian range/parity language is likely to have several
  variants across the two sites, and the Phase 1 parser needs to handle
  all of them, not just the first one you happen to see.
- **ENA planned vs. emergency outages.** Not yet confirmed whether both
  types appear on the single fetched page, or whether emergency ones
  need a separate URL/fetcher entirely. Compare a few days of ENA
  `RawContent` rows against each other — if you only ever see one
  "kind" of announcement, that's a strong signal the other type lives
  elsewhere and needs its own fetcher before Phase 1 can consider ENA
  data complete.
- **Veolia web vs. Telegram sync.** Once both sources have a few days of
  data, do a manual side-by-side: do the same outages show up on the
  website and in the Telegram channel, with matching times/addresses? Or
  does one lead the other, or carry outages the other doesn't? This
  directly decides the Phase 1 dedup/reconciliation strategy (the
  top-level plan deliberately deferred this decision for exactly this
  reason). If you notice a pattern early, jot it down — it'll save
  re-deriving it later from a larger, noisier dataset.
- **Marz/city labeling consistency.** Every structured outage record is
  supposed to carry whatever marz/city the source page attaches to it
  (per the top-level plan's nationwide-matching decision). While
  reviewing raw dumps, note whether marz/city shows up in a consistent,
  easily-extractable spot (e.g. always the first line of a Telegram
  post, as seen in the one sample fetched so far) or if it's
  inconsistent enough to need special-casing.
- **Telegram post structure drift.** The one real sample seen so far
  (`ingestion/tests/fixtures/veolia_telegram_sample.html`) follows a
  clean template: marz/city + date in a headline, then a structured
  Armenian body with a fixed "starts at X, ends at Y, affects Z" shape.
  Confirm this holds across many posts before assuming it's the format
  — one sample is not a spec.
- **Rate of `unchanged` vs `ok` in run summaries.** If a provider is
  showing `unchanged` on almost every poll, that's expected during
  quiet periods. If ENA or Veolia-web *never* shows `unchanged` even
  when you'd expect a stable page (e.g. because the page embeds a
  timestamp or session token that changes on every load regardless of
  actual content), the change-detection in §2.3 becomes useless for that
  source and worth revisiting — possibly by stripping known-volatile
  substrings before comparing, once you know what they are.

None of the above blocks Phase 0.5 from being considered "done" — the
point of this section is purely to make sure the multi-day observation
window (task 10) produces notes, not just a pile of HTML nobody looked
at closely until Phase 1 design day.
