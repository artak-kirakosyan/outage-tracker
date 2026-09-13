# Phase 1.3 — Users, Matching & Notifications Plan

Companion to `docs/project-plan.md` §5.3. Scoped to the last Phase 1 slice:
`Address`/`User` models, matching outages against addresses, notifications,
and the Telegram bot CRUD flow. Branch: `phase-1.3/users-addresses`.

## Status

| Task | Status |
|---|---|
| `Region` enum (`common/enums.py`) | **Done** |
| `Address`/`User` models (`accounts/`) | **Done** |
| Matching layer (`matching/`) | **Done** |
| `NotificationLog` model + compute-and-log step (`notifications/`) | **Done** |
| Telegram bot (CRUD + delivery) | Not started |

## Decisions locked in during review

- **Geography:** a new `Region` enum (`common/enums.py`), not a general
  canonical-marz module. Starts with `YEREVAN` and `ARARAT` only,
  expandable as coverage grows. Named `Region` rather than `Marz` because
  Yerevan is a city with marz-equivalent administrative status, not
  itself a marz, and the enum needs to represent both without misnaming
  either.
  - `OutageAnnouncement.marz` (`processing/models.py`) stays free text,
    unchanged — it's parsed verbatim from source and shouldn't be
    constrained to what `Region` currently covers. The enum only
    constrains `Address.region` and (later) the matching layer's
    canonicalization step.
  - Canonicalization turns out smaller than it first looked: both
    parsers already store Yerevan canonically (`"Երևան"`); only real
    marzes come out genitive/inflected. So the eventual inflection map
    needs exactly one entry today — `Արարատի → Արարատ` — not a general
    system. Add entries as `Region` grows.
- **Place names:** no enumerated lists anywhere except `Region`.
  Settlement/city and (deliberately, for consistency) Yerevan's
  districts are both plain free text on `Address`, matched by exact
  string for v1. `district_or_city` and `street` are plain `CharField`s
  rather than `choices`/FK so an admin-managed list can be introduced
  later as a data migration, not a schema change.
- **Provider scoping:** an `Address` is not tied to specific providers —
  one address matches against every provider's announcements. No
  `provider` field on `Address`. If a future paywall needs to scope an
  address to specific providers, that's an additive field then, not a
  redesign now — the same reserved-but-unused shape `Provider.GAZPROM`
  already uses elsewhere in this codebase.
- **Schema genericity:** `User` identity is `(channel, external_id)`, not
  a dedicated `telegram_id` field. Only `Channel.TELEGRAM` exists today
  (kept in `common/enums.py`, not inlined into `accounts/models.py`,
  since the future `NotificationLog.channel` will need the same enum).
  This keeps a future channel a new enum value, not a rename or a
  migration touching every table with a FK to `User`.
- **Gazprom:** stays parked, unchanged from the existing phasing.

## Matching layer — implemented as designed, with one addition

Built as `matching/geography.py` (canonicalization) + `matching/matcher.py`
(pure `find_matches_for_address(address) -> list[Match]`, no persistence).
Matches the design below exactly, plus one thing that only became clear
while writing it:

- **Geography filter:** `Address.region` vs `OutageAnnouncement.marz`, via
  the one-entry inflection map described above.
- **Veolia matches** (has `OutageLocation` rows): street match
  (normalized case/whitespace, not fuzzy in v1) + house-number
  range/parity check. The sub-numbered range rule (`67-80/2` → implicit
  `/1` floor) is flagged in `docs/data-patterns.md` §4 as *our own
  assumption, not provider-confirmed* — carried into the code as a
  boundary-only check (interior numbers always match); `confidence="high"`.
- **ENA planned matches** (`raw_address_text` only, no `OutageLocation`
  rows): shipped as-is, no gating. Matched by substring search against
  the raw text — street-name granularity only, no house-number check, so
  it *over-matches* by design (a user at house 2 and a user at house 200
  on the same named street both match); `confidence="low"`.
- **New: `parse_status=FAILED` announcements are excluded from matching
  entirely.** Not in the original design — became obvious once building
  against real code: a failed ENA parse's `raw_address_text` is the
  *entire unparsed block* (see `ena_planned.py`'s failed branch), not a
  real address list, so substring-matching against it would be noise,
  not signal, and would silently produce false positives no differently
  shaped than a real match.
- `Match(address, announcement, confidence)` is returned, not persisted
  — see `notifications/compute.py` for what turns it into a logged row.

### Follow-up: bounding the query by time (performance)

`OutageAnnouncement` is append-only and never pruned, same as
`RawContent` — the original `find_matches_for_address` queried it with
only a `marz` filter, so the query got slower forever as the table
grew, independent of how many addresses or announcements were actually
still relevant. This wasn't caught during the original review; see the
conversation for why (short version: nothing about correctness testing
would surface an unbounded-growth issue, and the closest in-codebase
precedent, `RawContent.processed`, didn't get pattern-matched against).

Fixed by bounding `_relevant_announcements()` by time instead of a
"seen it already" flag (a flag doesn't work here -- a brand-new
`Address` still needs to be checked against an outage that's still
ongoing, however old the row is):

- An announcement with a real `ends_at` is a candidate until
  `MATCH_END_GRACE_HOURS` (default 6) after it ends.
- An announcement with no `ends_at` (some "partial" ENA parses never
  get a structured end time) falls back to `last_seen_at` recency
  within `MATCH_STALE_WITHOUT_END_DAYS` (default 3), since there's no
  real end time to check against.

Both are env-configurable settings, following the same pattern as the
fetch-interval settings. Supported by a new `(marz, ends_at)` index on
`OutageAnnouncement` (`processing/migrations/0002_...`) so the bounded
query itself doesn't degrade as the historical table grows underneath
it.

**Not fixed yet, on purpose:** `notifications.compute_pending_notifications()`
still does one `get_or_create` per matched pair rather than batching
lookups/inserts. Once the announcement side is bounded this isn't the
dominant cost anymore, but it's still worth doing — separate follow-up.

## Notifications — implemented as designed

- `notifications.NotificationLog` — `user`, `address`,
  `outage_announcement` (FK), `channel`, `match_confidence`, `status`
  (`pending`/`sent`/`failed`), `created_at`, `sent_at`.
- `notifications.compute.compute_pending_notifications()` — the
  "compute matches + log intended notifications" half, kept separate
  from "actually call the Telegram API" as designed, so it's fully
  testable without a live bot token. Idempotent via `get_or_create` on
  `(address, outage_announcement)`.
- `compute_notifications` management command runs it manually for now;
  wiring it into `run_scheduler` (or a bot-triggered flow) is part of
  the bot task below, not done yet.
- Delivery (`status` transitioning to `sent`/`failed`, actually calling
  Telegram) is intentionally not built — that's the bot's job.

## Bot — design notes for the next slice

- New `bot/` app, `python-telegram-bot` v20+ (async), replacing the old
  v12 single-script bot.
- Scope: register, add/edit/delete address (guided multi-step form: region
  → city → street → number), list my addresses, list recent
  notifications. Delivery of new-match notifications reuses this same
  bot instance.
- Polling, not webhook, for v1 — consistent with the project's existing
  "simple over clever" calls (in-process scheduler threads, no Celery).
  Runs as its own `docker-compose` service (`bot`), separate from
  `scheduler`, so a bot restart doesn't interrupt fetching.
- **Open, not urgent:** what a user outside Yerevan/Ararat sees when
  trying to register an address — reject, "coming soon," or
  register-with-no-matching-yet. Doesn't affect schema work; fine to
  decide once this task is actually in front of us.
- Needs a `TELEGRAM_BOT_TOKEN` env var + `.env.example` entry.
