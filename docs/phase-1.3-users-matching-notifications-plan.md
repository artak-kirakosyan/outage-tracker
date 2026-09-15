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
| Telegram bot (CRUD + delivery) | **Done** |

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
- **Added while building the bot's `check_match` testing command:**
  the per-announcement text/location matching logic (the two bullets
  above) was pulled out into its own
  `matching.matcher.match_confidence_for_announcement(address,
  announcement)`, independent of `_relevant_announcements()`'s
  time-window bound. `find_matches_for_address()`'s behavior is
  unchanged; this only made the pure "does the text match" check
  reusable for testing one hand-picked pair without it being excluded
  for being outside the production time window.

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
- `compute_notifications` management command runs it manually; also run
  by `run_scheduler` (see the Bot section below for the delivery half).
- Delivery: `notifications/send.py`.
  `send_pending_notifications()` sends every `PENDING` row in one
  batch (used by the scheduler job and the `send_notifications`
  command) via the Telegram Bot API, setting `sent`/`failed` per row.
  A `FAILED` row is not retried automatically on the next run — left
  for manual investigation rather than retried forever against a
  possibly-permanently-bad chat id. `send_notification(log)` sends a
  single row instead, used by `matching.check_match` (see the Bot
  section) so a manual test doesn't sweep up unrelated `PENDING` rows.

## Bot — implemented as designed, with one addition

- `bot/` app, `python-telegram-bot` v20+ (async), polling (not
  webhook) — consistent with the project's existing "simple over
  clever" calls (in-process scheduler threads, no Celery).
  `run_bot` management command starts it; runs as its own
  `docker-compose` service (`bot`), separate from `scheduler`, so a
  bot restart doesn't interrupt fetching.
- Scope: `/start` registers a `User`; add/edit/delete address via a
  guided, inline-keyboard conversation (region → city → street →
  number → optional sub-number → optional label → confirm); `/myaddresses`
  lists addresses as buttons, tapping one shows its details plus
  Edit/Delete/back buttons — **the user never types or needs to know an
  address id**, unlike an earlier draft of this design. `/notifications`
  lists recent `NotificationLog` rows. Editing overwrites the whole
  record rather than patching individual fields, kept simple for v1.
  Deleting asks for confirmation first.
- `bot/services.py` holds the sync DB operations backing the handlers
  (Django's ORM is sync-only; handlers wrap each call with
  `sync_to_async`), kept separate so it's unit-testable without any
  Telegram/PTB mocking.
- Delivery of computed notifications reuses `notifications/send.py`
  (see the Notifications section above), not bot-instance-specific
  code — the bot process only handles the conversation.
- **New: `matching.check_match` management command**, added after
  real-address testing surfaced a gap — there was no way to construct
  a specific test address and a specific test announcement and confirm
  the match/notification actually fires without waiting on the
  scheduler's time-bounded scan (`matching/matcher.py`'s
  `_relevant_announcements()`) or a live outage. `check_match --address
  <id> --announcement <id>` reports the geography check, the
  text/location match result, and (if matched) previews the exact
  notification text; `--send` additionally logs and delivers it via
  Telegram for a real end-to-end check.
- **Resolved during review, not left open:** users outside
  Yerevan/Ararat are allowed to register an address freely, same as
  any other region — no reject / "coming soon" gate. `Region` currently
  only covers two marzes, so an address elsewhere simply won't match
  anything yet; the rest of `Region` is expected to be filled in later
  (see `docs/project-plan.md` §7).
- `TELEGRAM_BOT_TOKEN` and `NOTIFICATION_INTERVAL_MINUTES` env vars
  added to `.env.example`.
- **Known simplification, not a bug:** `Address` has no `active`/
  paused flag — a user who wants to stop matching on one address has
  to delete it. Noted as a future enhancement, not built now.
