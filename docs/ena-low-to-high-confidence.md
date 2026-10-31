# ENA Matching: From Low Confidence to High Confidence

Snapshot of the full ENA pipeline (HTML page → parsing → storage →
matching → notification), what actually works today, and what still
needs to change for ENA-sourced matches.

## Why ENA matches used to be "low confidence"

`matching/matcher.py` picks a path per announcement: if it has
`OutageLocation` rows, do a structured street+range/parity match
(`confidence="full_address"`); if not, fall back to a substring search on
`raw_address_text` (`confidence="street_only"`).

Until the ENA location parser landed, every ENA announcement took the
second path, because `processing/parsers/ena_planned.py` never produced
`OutageLocation` rows — a deliberate v1 fidelity split
(`docs/phase-1-processing-plan.md` §4).

**Why the decomposition was deferred:** ENA's address text nests a
second heading level *inside* a single time-slot's text (village names
like `"Զոլաքար գյուղ՝ 17-րդ, 18-րդ..."`, using the same `՝` marker a
region heading uses), mixed freely with plain street lists, business
names, numbered-street ranges, and qualifiers (`մասնակի`/`ամբողջությամբ`)
whose scope is often ambiguous across multiple list items. That's a
meaningfully bigger grammar than Veolia's flat comma-list.

## Status of the location parser (2026-09-15)

✅ **Done.** `processing/parsers/ena_locations.py` decomposes
`raw_address_text` into `OutageLocation` rows (nested localities,
qualifiers, plural village runs, ordinal streets, non-address entities).
New ENA announcements get locations on create; existing rows are
rebuildable via `manage.py backfill_ena_locations`.

Matching now uses the structured `FULL_ADDRESS` path when locations
exist, with locality scoping for multi-city announcements under one
marz. `STREET_ONLY` raw-text fallback remains only when an announcement
has zero locations.

Remaining known gaps:
- District spelling variants (`Մալաթիա Սեբաստիա` vs `Մալաթիա-Սեբաստիա`)
  still need canonicalization for locality checks.
- `մասնակի` is stored on `OutageLocation.qualifier` but does not yet
  change notification copy.
- Ambiguous qualifier scope (`գյուղ1, գյուղ2 մասնակի`) applies to the
  last item only.

## The pipeline, stage by stage

### 1. Fetch — `ingestion/fetchers/ena.py`
✅ Solid. Single GET to `ena.am/Info.aspx?id=5&lang=1`, stores the whole
page verbatim. Live-fetching confirmed working against the real site.

### 2. HTML extraction — `processing/html_extract.py::extract_ena_planned_section`
✅ **Confirmed working.** Analysis of 120 real DB fetches confirmed the `ctl00_ContentPlaceHolder1_attenbody` ID is stable and correctly extracts the planned section text.

### 3. Parsing — `processing/parsers/ena_planned.py` + `ena_locations.py`
✅ Region/time/date extraction is solid and tested against real historical fetches.
✅ Address-list decomposition into `OutageLocation` (see above).
**Fixed (2026-09-15):** ENA's `&ndash;` (en-dash) HTML entity for time
ranges is normalized via `normalize_multiline()` before parse.

### 4. Persistence — `processing/management/commands/process_raw_content.py`
✅ Mechanics are solid: idempotent via a content hash, correctly
reconciles a "preliminary" sighting into "confirmed" without
duplicating, and creates ENA `OutageLocation` rows on announcement
create. ❌ **Only ever processes the "Պլանային անջատումներ"
(planned) section.** ENA's other section — the actual
"Վթարային և կանխարգելիչ անջատումներ" (emergency/preventive) table —
is explicitly out of scope. That table's HTML sits in `RawContent.content`
untouched (nothing lost), just never parsed.

### 5. Matching — `matching/matcher.py`
With locations present, ENA uses the same structured path as Veolia
(street equality / house range / whole-area vs district). Locality
scoping reduces false positives across cities listed in one marz block.
`STREET_ONLY` substring matching remains only as a fallback when
decomposition produced no rows.

### 6. Notification logging
Works correctly on its own terms (idempotent, tested). Downstream of
matching confidence.

### 7. Monitoring
✅ Admin pipeline-health dashboard surfaces fetch/extraction/parse/
notification failures (see `templates/admin/index.html`).

## What remains

1. ~~Build a real ENA address-location parser~~ **Done** (see above).
2. **Decide on and scope the emergency/preventive table** — whether
   it's worth the "12,000-row watermarking problem" and abbreviation
   unknowns already documented, given it's the actually time-sensitive
   half of ENA's data.
3. District spelling canonicalization for locality matching.
4. Optional: surface `մասնակի` in notification copy.
