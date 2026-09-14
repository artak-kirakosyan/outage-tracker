# ENA Matching: From Low Confidence to High Confidence

Snapshot of the full ENA pipeline (HTML page → parsing → storage →
matching → notification), what actually works today, and what needs to
change for ENA-sourced matches to reach the same confidence level as
Veolia's.

## Why ENA matches are "low confidence" today

`matching/matcher.py` picks a path per announcement: if it has
`OutageLocation` rows, do a structured street+range/parity match
(`confidence="high"`); if not, fall back to a substring search on
`raw_address_text` (`confidence="low"`). Every ENA announcement takes the
second path, because `processing/parsers/ena_planned.py` never produces
`OutageLocation` rows in the first place — that's a pre-existing scope
decision (`docs/phase-1-processing-plan.md` §4), not something the
matching layer introduced.

**Why the decomposition was never built:** ENA's address text nests a
second heading level *inside* a single time-slot's text (village names
like `"Զոլաքար գյուղ՝ 17-րդ, 18-րդ..."`, using the same `՝` marker a
region heading uses), mixed freely with plain street lists, business
names, numbered-street ranges, and qualifiers (`մասնակի`/`ամբողջությամբ`)
whose scope is often ambiguous across multiple list items. That's a
meaningfully bigger grammar than Veolia's flat comma-list, and ENA's
planned block was judged less real-time-critical than Veolia's emergency
feed — so the effort went into Veolia's decomposition first.
`raw_address_text` is kept verbatim specifically so a real ENA location
parser can be built later without re-fetching anything.

## The pipeline, stage by stage

### 1. Fetch — `ingestion/fetchers/ena.py`
✅ Solid. Single GET to `ena.am/Info.aspx?id=5&lang=1`, stores the whole
page verbatim. Live-fetching confirmed working against the real site.

### 2. HTML extraction — `processing/html_extract.py::extract_ena_planned_section`
⚠️ **The biggest actual risk in the whole pipeline, and it's already
flagged as unresolved.** Looks for an element whose `id` contains
`"attenbody"` and pulls its text out. The function's own docstring:
*"no live-fetched sample of the actual page was available while writing
this... Confirm against a live fetch before relying on this for real ENA
data."* If that id guess is wrong, `extract_ena_planned_section` returns
`None`, `process_raw_content` logs an error, bumps `extraction_failed`,
and **zero announcements get created from that fetch** — silently, with
nothing actively alerting on it.

### 3. Parsing — `processing/parsers/ena_planned.py`
✅/⚠️ Region/time/date extraction is well-tested and handles real
complexity (two day-block shapes, Dec→Jan rollover, the
`մարզ`/`վարչական շրջան` discriminator for a real region heading vs. a
locality sub-heading). But it's only ever been validated against **two
distinct historical text samples** — both reached 100%
`parse_status="ok"`, a good sign but a small sample for open-ended
government prose that could drift in phrasing over time.
`parse_status` (`ok`/`partial`/`failed`) exists as a safety net and is
filterable in `/admin/`, but nothing currently watches it proactively.

### 4. Persistence — `processing/management/commands/process_raw_content.py`
✅ Mechanics are solid: idempotent via a content hash, correctly
reconciles a "preliminary" sighting into "confirmed" without
duplicating. ❌ **Only ever processes the "Պլանային անջատումներ"
(planned) section.** ENA's other section — the actual
"Վթարային և կանխարգելիչ անջատումներ" (emergency/preventive) table,
~12,000 rows per `docs/data-patterns.md` §1.1 — is explicitly out of
scope. That table's HTML sits in `RawContent.content` untouched (nothing
lost), just never parsed. **Practically: ENA's genuinely urgent outages
don't reach this notification system at all right now** — only
scheduled/planned maintenance does.

### 5. Matching — `matching/matcher.py`
Four separate, real gaps, not just "no house-number check":
- **No house-number granularity** — a user at house 2 and house 200 on
  the same street both match.
- **Substring false positives from partial name overlap** — the check
  is literally `street_name in raw_text`, so e.g. a street named
  "Կենտրոն" matches any announcement mentioning "Կենտրոնական" (a
  different, longer name that contains it as a substring).
- **Nested-locality structure isn't respected.** `raw_address_text` is
  scoped per (region, time-slot), but multiple villages can each list
  their own streets within that slot. A substring match doesn't know
  which village a street belongs to — two different villages with a
  same-named street in one time-slot are indistinguishable to it.
- **Qualifier scope is invisible.** Whether it's `մասնակի` (partial) or
  `ամբողջությամբ` (entire) doesn't factor in at all — a substring hit
  gives no information about how much of the street is actually
  affected.

### 6. Notification logging
Works correctly on its own terms (idempotent, tested), but is purely
downstream — it inherits every gap above with no way to tell them
apart. A `NotificationLog` row with `match_confidence="low"` could mean
any of the four matching gaps, or a completely legitimate match, with
no way to distinguish which today.

## Summary

The parsing and persistence logic for what ENA data *does* get
processed is reasonably solid and tested. The extraction step feeding
it has never been checked against a real page. An entire category of
ENA outages (the actually urgent ones) isn't processed at all. And the
matching layer's low confidence on ENA isn't just "no house number" —
it's four separate, real gaps stacked on top of an already narrower
data source.

## What "high confidence" would actually require

Roughly in the order that unblocks the most downstream value:

1. **Verify (or fix) the `attenbody` extraction against a real live
   fetch.** Everything else is moot if this is silently returning
   `None`.
2. **Build a real ENA address-location parser**, decomposing
   `raw_address_text` into `OutageLocation` rows the way Veolia's
   parser does — including handling the nested locality sub-headings
   and qualifier scope that made this out of scope for v1. This is the
   single change that would let ENA matches use the same structured
   `confidence="high"` path Veolia already has.
3. **Decide on and scope the emergency/preventive table** — whether
   it's worth the "12,000-row watermarking problem" and abbreviation
   unknowns already documented, given it's the actually time-sensitive
   half of ENA's data.
4. **Add monitoring on `parse_status` distribution** (and
   `extraction_failed`) so drift or breakage surfaces proactively
   instead of requiring someone to check `/admin/`.
