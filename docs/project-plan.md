# Utility Outage Notifier — Plan

## 1. Problem Statement

The existing bot (Telegram, Python, `python-telegram-bot` v12) is a single
cron-triggered script: it loads a static `users.json`, scrapes ENA
(electricity) and Veolia (water) on every run, matches against each user's
single hardcoded address, and sends a Telegram message. Nothing is
persisted — no raw data, no parsed outages, no notification history. Each
user maps to exactly one address, address matching is a naive substring
search with no range/parity logic, and there's no way to register, update,
or manage addresses without editing a file by hand.

We want a real system:

- Users can register and manage **multiple addresses** (CRUD).
- Outage data is fetched, **stored raw**, then parsed into structured
  records — decoupled so each stage can be built, tested, and re-run
  independently.
- Matching accounts for how providers actually write addresses (plain
  ranges, even/odd-only ranges, comma-separated lists with sub-numbers,
  or a whole street with no numbers at all).
- Matching is **nationwide** (not just Yerevan), with marz/district
  surfaced in notifications so users can spot false positives from
  same-named streets elsewhere.
- Notifications sent to users are themselves stored, for later analysis.
- The architecture leaves clean extension points for a future paywall,
  without building any entitlement logic now.
- A third provider (Gazprom) and emergency-vs-planned distinctions can be
  added later without reshaping the schema.

## 2. Phasing Overview

| Phase | Goal | Status |
|---|---|---|
| **0.5** | Raw outage ingestion into storage. No parsing, no users, no notifications. | **Done** |
| **1** | Raw → structured outage parsing (address-range logic); Users/Addresses CRUD via bot; matching + notifications + notification history. | **In progress** — raw→structured parsing slice done; models, CRUD, matching, and notifications not started |
| **2** | Gazprom added as a third provider via the same abstraction. | Not started |
| **3** | Paywall/entitlements activated on the reserved extension points. | Not started |

## 3. Architecture & Key Decisions

- **DB layer: Django (ORM + migrations + admin), not a full Django web app.**
  Used purely for schema management and free local inspection via Django
  admin. The bot process and scheduled fetch jobs are separate
  long-running/one-shot processes that call `django.setup()` and use the
  ORM — no views/templates/webhook server needed.
- **Storage: SQLite via the Django ORM.** No raw `sqlite3` calls, so
  switching `DATABASES` to Postgres later is a config change, not a
  rewrite.
- **Deployment: Docker Compose**, run locally (no hosting needed yet),
  structured so it can move to a real host unchanged later. A `scheduler`
  service runs the fetchers continuously; an optional `admin` service
  exposes Django admin for browsing `RawContent`. Both verified working
  end-to-end, including a continuous production run of the scheduler.
- **Raw ingestion is provider-agnostic.** One fetcher interface, one
  `RawContent` table, tagged by `provider` and `source_type` — this is
  what lets Gazprom slot in later with zero schema change. `Provider` now
  lives in `common/enums.py` (shared by `ingestion` and `processing`
  rather than defined once inside `ingestion.models`).
- **Active sources: ENA and Veolia's Telegram channel.**
  - `ENAFetcher` — `https://www.ena.am/Info.aspx?id=5&lang=1`.
  - `VeoliaTelegramFetcher` — scrapes Telegram's public, unauthenticated
    preview page at `https://t.me/s/VeoliaJur` instead of the Bot API
    (would need bot-admin on Veolia's own channel) or a userbot/MTProto
    session (account-flag risk, overkill for a public channel).
  - `VeoliaWebFetcher` (`interactive.vjur.am`) exists but is **disabled
    by default** (`VEOLIA_WEB_FETCH_ENABLED=false`) — the site is
    unreliable and frequently down. Code stays in place in case it
    becomes reliable again; Telegram is the operational water-outage
    source.
- **Raw content is stored twice, redundantly:** once in the DB (source of
  truth) and once mirrored to a file on disk, for convenient manual
  eyeballing while designing the parser.
- **Raw-layer change detection.** A fetch byte-identical to the last
  successful fetch for that `(provider, reference)` isn't written as a
  new row — no DB row, no file dump. Plain byte-equality, not hashing.
- **Scheduler: in-process daemon threads**, one per provider, own
  interval, per-job exception isolation. Per-provider enable/disable
  flags are consulted only by the scheduler — a `fetch_*` command run
  directly always runs regardless.
- **Phase 1 fidelity split: Veolia (full) vs. ENA planned (shallow).**
  Veolia's Telegram posts get full structured decomposition into
  per-location rows (street, house range, parity, kind). ENA's
  planned-outage prose gets structured date/region/time-window fields,
  but its address portion stays one verbatim raw-text string — no
  per-location decomposition. Decided after real-data review: ENA's
  planned block nests locality-level sub-headings inside its address
  text in a way that needs meaningfully more grammar than Veolia's flat
  comma list.
- **ENA's emergency/preventive table is explicitly out of scope for
  Phase 1 v1**, confirmed by direct instruction — it removes the
  highest-complexity, lowest-value work found during data review (a
  12,000-row watermarking problem, several unresolved abbreviations, a
  street→lane→house hierarchy).
- **Address-range parsing rules**, confirmed against real collected data:
  a range like `20-40` is matched on the *main* number regardless of
  sub-number; the sub-number only matters in an explicit comma-separated
  list. Ranges can carry a sub-number on either or both endpoints
  (`67-80/2`), and a parity word (odd/even) can qualify either a range or
  an explicit list.
- **Geography is nationwide from the start.** Marz/district isn't used
  for filtering yet (needs the canonical district/city list), but every
  structured outage record carries whatever marz/city the source
  attaches to it, for surfacing as a false-positive hint later.
- **Paywall: intention reserved, nothing built yet.** No `Plan`/
  `Subscription` model exists in the codebase at all — not even as an
  unused stub. The plan is still to add one, unused, ahead of
  entitlement checks eventually sitting in front of "create address" /
  "attach a provider to an address," so the check can be dropped in
  later without restructuring the CRUD flow — but unlike the `Provider`
  abstraction (which already reserves `GAZPROM`), this hasn't been
  scaffolded.
- **Notification history**: schema settled (one row per user, address,
  outage, channel, sent_at) but nothing built — no notifications exist
  yet.

## 4. Phase 0.5 — Status: Done

Verified against the live sites (ENA and the Veolia Telegram channel both
fetch correctly), Docker Compose runs end-to-end, and the scheduler has
run continuously in production with no issues. Real data has been
collected and reviewed (`outage-data-patterns.md` → superseded by
`outage-data-patterns-v2.md`): 35 ENA fetches, 113 Veolia-Telegram
fetches, all Veolia-web fetches erroring (consistent with it being
disabled by default).

Schema: a single `ingestion.RawContent` model — `provider`, `source_type`,
`reference`, `content`, `fetched_at`, `fetch_status`, `error_message`,
`dump_file_path`, and `processed` (reserved, unused until Phase 1's
parser output is persisted).

## 5. Phase 1 — Status: In progress

Split into three slices; only the first is done.

### 5.1 Raw → structured parsing — Done

- `common/enums.py` — `Provider` (shared by `ingestion` and
  `processing`).
- `processing/normalize.py` — nbsp/dash/whitespace normalization.
- `processing/armenian_dates.py` — month-name lookup.
- `processing/address_grammar.py` — Veolia's comma-list address grammar:
  whole area, whole street, house-number range, street-number range
  (numbered-street districts like Նոր Արեշ/Վարդաշեն), and parity
  (odd/even).
- `processing/parsers/veolia_telegram.py` — full structured parse of a
  Telegram post (marz/district, time window, decomposed locations).
- `processing/parsers/ena_planned.py` — shallow parse of ENA's planned
  section (date/region/time window structured; address kept verbatim).
- Parsers are tested against every distinct real historical sample
  collected in Phase 0.5, not synthetic fixtures — including the
  edge cases found during review (two-district `և`-joins, missing
  grammatical suffixes, source-side typos, the Dec/Jan year rollover,
  and the numbered-street vs. house-number distinction).
- Confirmed real-data resolutions carried over from
  `outage-data-patterns-v2.md`: `Ա/Ձ` = individual entrepreneur;
  `Հ. Մալյան/Արաբկիր 45 փող.` is a renamed-street annotation, not a
  second address.

### 5.2 Structured storage — Done

- `processing/models.py` — `OutageAnnouncement` / `OutageLocation`
  Django models + migration.
- `process_raw_content` management command tying `RawContent.processed`
  to the parsers above, using the idempotency keys already designed
  (Telegram's `data-post` id for Veolia; a content hash for ENA), wired
  into `run_scheduler` on its own interval.
- `starts_at`/`ends_at` localized to `Asia/Yerevan` in the command.
- `processing/html_extract.py` — a previously-undocumented gap found
  during implementation: neither parser actually operates on the full
  page HTML `RawContent.content` stores; this module splits/extracts
  the section or posts each parser expects. See
  `docs/phase-1-processing-plan.md` §9 for the full writeup, including
  the caveat that the ENA extractor is unverified against a live fetch.

### 5.3 Users, matching, notifications — Not started

- `Address`/`User` models + CRUD via a rewritten, async Telegram bot
  (`python-telegram-bot` v20+).
- Matching layer: address ↔ outage, using marz/district once the
  canonical list is available.
- Notifications: send + persist history.

## 6. Phases 2–3

- **Phase 2:** Gazprom fetcher added via the existing `Provider`
  abstraction; no changes needed elsewhere in the pipeline.
- **Phase 3:** Scaffold and activate a `Plan`/`Subscription` model with
  real entitlement checks (1 address / 1 provider on free tier, or
  whatever the final rule is) in front of address/provider-attach
  actions.

## 7. Open Items

- **Canonical marz/district/city list** — still pending; blocks
  geographic filtering and matching.
- **Marz names are stored in inflected/genitive Armenian form**
  (e.g. `Սյունիքի`, not `Սյունիք`) — needs normalizing to canonical form
  before matching against a canonical list.
- **Sub-numbered range-endpoint matching rule** (e.g. `67-80/2`) — the
  "implicit `/1` floor" interpretation is a documented assumption, not
  provider-confirmed; parsing stores what's seen, matching-time
  behavior still needs deciding/validating.
- **Parity scope simplification** — a parity word trailing a whole
  comma-list (no number of its own) isn't retroactively applied to
  earlier items in the list; flagged for revisit if it turns out to
  matter.
- **V-9 lane/dead-end sub-identifiers** (e.g. `Կ.Ուլնեցու 1 Նրբ.`) parse
  as an ordinary house-number range; structurally harmless but
  semantically imprecise, low frequency, not fixed.
- **`զ/ծ` abbreviation** (handful of ENA addresses) — still unresolved;
  moot for now since ENA's emergency table is out of Phase 1 v1 scope.
- **Veolia web vs. Telegram sync** — moot while Veolia-web stays
  disabled; revisit if it's ever re-enabled.
- **Documentation catch-up** — `README.md` and `docs/phase-0.5-plan.md`
  still describe live fetching as unverified from inside the sandbox;
  that's since been confirmed working and both docs need a pass to
  drop the caveat and note the VeoliaWeb-disabled decision.
- **Gazprom** — explicitly out of scope until Phase 2; only the
  `Provider` abstraction anticipates it.
