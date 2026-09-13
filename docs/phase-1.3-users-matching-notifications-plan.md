# Phase 1.3 — Users, Matching & Notifications Plan

Companion to `docs/project-plan.md` §5.3. Scoped to the last Phase 1 slice:
`Address`/`User` models, matching outages against addresses, notifications,
and the Telegram bot CRUD flow. Branch: `phase-1.3/users-addresses`.

## Status

| Task | Status |
|---|---|
| `Region` enum (`common/enums.py`) | **Done** |
| `Address`/`User` models (`accounts/`) | **Done** |
| Matching layer | Not started |
| `NotificationLog` model + send logic | Not started |
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

## Matching layer — design notes for the next slice

- **Geography filter:** `Address.region` vs `OutageAnnouncement.marz`, via
  the one-entry inflection map described above.
- **Veolia matches** (has `OutageLocation` rows): street match
  (normalized case/whitespace, not fuzzy in v1) + house-number
  range/parity check. The sub-numbered range rule (`67-80/2` → implicit
  `/1` floor) is flagged in `docs/data-patterns.md` §4 as *our own
  assumption, not provider-confirmed* — worth carrying that uncertainty
  into the notification copy ("possible match") rather than presenting
  it as certain.
- **ENA planned matches** (`raw_address_text` only, no `OutageLocation`
  rows): shipping in v1 as-is, no gating behind a beta flag. Matched by
  substring/keyword search against the raw text instead of a structured
  comparison, because ENA's planned block is kept as one verbatim string
  per announcement rather than decomposed (`phase-1-processing-plan.md`
  §4). Concretely: matching only works at street-name granularity —
  there's no house-number range to check, so a user at house 2 and a
  user at house 200 on the same named street both match an announcement
  that only actually affects part of it. This means ENA-sourced
  notifications will *over-match* (false positives on house number,
  never on street name, never under-match). Worth a line in the
  notification copy ("this covers part of your street — check the
  details") so the lower confidence is legible to the user.
- Output a `Match(address, announcement, confidence)` value, not
  persisted directly — persistence happens in the notification step, so
  matching stays a pure, replayable function like `processing/parsers`.

## Notifications — design notes for the next slice

- `NotificationLog` — `user`, `address`, `outage_announcement` (FK),
  `channel`, `sent_at`, `status`.
- Idempotency: `get_or_create` on `(address, outage_announcement)`. A
  `process_raw_content` re-run that only bumps an existing
  announcement's `last_seen_at` must not re-trigger a notification.
- Split "compute matches + log intended notifications" from "actually
  call the Telegram API" — same reasoning as the raw/structured split:
  the matching+dedup logic stays fully testable without a live bot token
  or network access.

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
