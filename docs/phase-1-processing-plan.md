# Phase 1 — Raw → Structured Processing Plan

Companion to `utility-outage-notifier-plan.md` and the two
`outage-data-patterns*.md` docs. Scoped to the first slice of Phase 1:
turning `ingestion.RawContent` rows into structured outage data. Matching
(address ↔ outage) and notifications are still out of scope — this
covers parsing and storage only, per the agreed two-step split.

Branch suggestion: `phase-1/raw-to-structured`.

## 1. Scope (confirmed)

**In scope for v1:**
- ENA's **planned outages** prose section (`Պլանային անջատումներ`).
- Veolia's **Telegram channel** posts (`veolia_telegram`).

**Explicitly out of scope for v1:**
- **ENA's emergency/preventive table** (`Վթարային և կանխարգելիչ անջատումներ`).
  Confirmed out of scope per direct instruction. This also removes the
  most complex, lowest-value work identified during data review: the
  12,000-row watermarking problem, the `Ա/Ձ`/`զ/ծ` abbreviation
  mysteries, the lane/quarter hierarchy (E-5/E-6), and the
  hyphen-vs-sub-number ambiguity (E-7) — all of that lived only in this
  table.
- **Veolia's website** (`veolia_web`) — already disabled at the
  ingestion layer (unreliable, `VEOLIA_WEB_FETCH_ENABLED=false`), all 8
  rows in the reviewed db are errors. No processing work possible or
  needed.
- **Gazprom** — no fetcher exists yet (Phase 2).
- **Matching and notifications** — next step after this one.

## 2. What real data added beyond the patterns docs

The patterns docs were built from the same db but under-sampled the ENA
planned block specifically. Re-verified directly against
`RawContent` rows 2 and 18 (the only two distinct planned-block texts
across all 35 ENA fetches):

- **The planned block has two day-block shapes, not one.** "Confirmed"
  day-blocks are separated by a literal run of asterisks (`****...`)
  and open with the full company-name sentence. After the last one, a
  **`Պլանային անջատումների մասին նախնական տեղեկատվություն`**
  ("preliminary information") section follows, containing *further*
  day-blocks — separated only by a bare date heading, with a shorter
  opening sentence (no company-name prefix). Row 18 had 2 confirmed
  blocks (Sep 7, 8) + 4 preliminary ones (Sep 9, 10, 11, 14) — six
  day-blocks in one page fetch, not the two–three the patterns doc
  counted.
- **Locality-level sub-headings nest inside a single time-slot's
  address text**, using the same `՝` marker as top-level region
  headings (e.g. `Զոլաքար գյուղ՝ 2-րդ, 4-րդ ... ամբողջությամբ, 24-րդ
  փողոց մասնակի`). The reliable discriminator: a true region-level
  heading always contains `մարզ` or `վարչական շրջան`; anything else
  ending in `՝` is a locality inside the address text. This is what
  makes full decomposition of the ENA planned block meaningfully
  harder than Veolia's flat comma list (see §4 for the scope decision
  this drove).
- Additional location vocabulary confirmed real, previously undocumented:
  `նրբանցք`/`նրբ.` (lane), `փակուղի`/`փակ.` (dead-end), `շարքեր` ("rows"),
  `առանձնատներ` ("detached houses", a housing-type descriptor parallel
  to `շենքեր`), and numbered-*street* ranges (`7–12-րդ փողոցների`, a
  range over street numbers, not house numbers).
- Two variants of the trailing qualifier exist:
  `... և հարակից ոչ բնակիչ-բաժանորդներ` vs. `... և ոչ բնակիչ-բաժանորդներ`
  (with/without "adjacent").
- Real, confirmed ambiguity: `Ոսկետափ գյուղ, Այգավան գյուղ մասնակի` — unclear
  whether "partially" scopes to just Այգավան or both villages.
- **Veolia's data matched the docs closely.** One addition: real post
  text uses non-breaking spaces (`\xa0`) throughout — any regex/tokenizer
  must normalize these first or matches silently fail. Also confirmed:
  the `Հ. Մալյան/Արաբկիր 45 փող.` V-10 pattern is a **renamed-street
  annotation** (Arabkir 45 is the confirmed old name of what's now H.
  Malyan street), not an intersection or a second address — resolved,
  see §5.
- One confirmed **source-side typo**: one real post runs two words
  together with no space (`Շենքերիջրամատակարարումը`). Parser regexes
  need to tolerate this rather than fail the whole post over it.

## 3. Architecture

```
common/
  enums.py              # Provider (moved out of ingestion.models — no
                         # migration impact, TextChoices values are
                         # baked into migrations as plain tuples)
processing/
  normalize.py           # nbsp/dash/whitespace normalization
  armenian_dates.py       # month-name -> number lookup, shared
  address_grammar.py       # Veolia's comma-list grammar (street/range/parity)
  parsers/
    veolia_telegram.py      # full structured parse: headline + body + locations
    ena_planned.py           # shallow parse: date/region/time only, address kept raw
  models.py               # NOT YET BUILT — see §7
  tests/
    fixtures/
      veolia_posts.json      # all 40 distinct real posts, by data-post id
      ena_planned.json        # the 2 distinct real planned-block texts
    test_veolia_telegram.py
    test_ena_planned.py
```

`address_grammar.py` is Veolia-only for v1 (see §4) — despite living in
a shared-sounding module, it is not currently invoked by the ENA parser.
Kept as its own module rather than inlined into `veolia_telegram.py`
since a future full ENA-location parser would very likely reuse most of
this grammar (bare street, street+range, parity, sub-numbers) — only
ENA's heading structure around it differs.

## 4. Fidelity split: Veolia (full) vs. ENA planned (shallow)

**Decision, confirmed:** Veolia gets full structured decomposition into
`OutageLocation` rows (street, house range, parity, kind). ENA's planned
block gets structured `OutageAnnouncement` fields (date, region, time
window) but its address portion stays as one verbatim `raw_address_text`
string — **no `OutageLocation` rows are created for ENA in v1.**

This is a deliberate simplification, not a temporary bug: matching
against ENA planned outages will have to be substring/keyword-based
against `raw_address_text` until a future pass builds a dedicated parser
for its nested locality-heading grammar. Revisit if ENA turns out to be
a large share of what users actually need matched against.

## 5. Schema

```
OutageAnnouncement
------------------------------------------------
provider                  (ena | veolia_telegram)
outage_type                (planned | emergency)
is_preliminary              (bool — ENA only; Veolia always False)
marz                         (nullable text — "Երևան" for Yerevan too)
district_or_city              (nullable text)
starts_at / ends_at            (naive datetime; Django integration
                                 localizes to Asia/Yerevan — see §7)
raw_heading_text                 (verbatim: region/headline fragment)
raw_address_text                  (verbatim: the full address-list text —
                                    always populated, even when
                                    OutageLocation rows exist too)
external_ref                       (dedup key — see §6)
parse_status                        (ok | partial | failed)
first_seen_raw_content (FK -> ingestion.RawContent)
first_seen_at / last_seen_at

OutageLocation  (FK -> OutageAnnouncement; Veolia only in v1 — see §4)
------------------------------------------------
raw_fragment               (verbatim comma-item text)
kind                        (whole_area | whole_street | street_range | unparsed)
street                       (nullable)
house_low / house_low_sub      (int / nullable string — "1", "2Ա", etc.)
house_high / house_high_sub
parity                          (any | odd | even)
is_matchable                     (bool; False for `unparsed`)
```

Fields kept deliberately unused-for-now, reserved for when ENA planned
gets its own location parser (mirrors the project's existing pattern —
`RawContent.processed`, `Provider.GAZPROM`): `qualifier` (partial/entire,
ENA's `մասնակի`/`ամբողջությամբ`) and a `non_address` `LocationKind` value
for ENA's business/institution entries (P-3) — not added to the schema
yet since nothing produces them in v1, but noted here so adding them
later doesn't require re-deriving this decision.

## 6. Idempotency

Both `RawContent` sources repeat the same underlying content across many
fetches (ENA day-blocks persist on the page until their date passes;
Veolia's preview page always shows the last N posts, not just new ones)
— so processing must be safe to re-run against overlapping fetches
without creating duplicate announcements.

- **Veolia:** `external_ref` = Telegram's own `data-post` id (stable,
  confirmed unique across all 40 real posts). `get_or_create` on
  `(provider, external_ref)`.
- **ENA planned:** no natural id exists in the source. `external_ref` =
  a hash of `(date, region text, time window, raw_address_text)`. If ENA
  edits an existing block's address list, the hash changes and a new row
  is created rather than the old one being updated in place — accepted
  as a known limitation for v1 (the stale row is simply never
  reconfirmed via `last_seen_at`, not actively corrected).

## 7. Documented parsing assumptions / known simplifications

- **Street numbers vs. house numbers (fixed after review):** some
  outlying districts (Նոր Արեշ, Վարդաշեն, Մուշական, ...) number their
  *streets* rather than naming them — `Նոր Արեշ 12, 14 փողոցների` means
  streets 12 and 14 of Nor Aresh, not house numbers 12/14 on a street
  named "Նոր Արեշ". This was initially unhandled: the Veolia parser
  folded these into ordinary house-number `street_range` rows, silently
  wrong rather than flagged (didn't show up in `unparsed`, so the "0%
  unparsed" test-coverage stat overstated how clean the breakdown
  really was). Fixed via a new `street_number_range` kind, detected
  from the source's own trailing noun (`փողոց(ի/ներ/ների)` = "streets"
  vs. `շենք(եր)(ի)`/`առանձնատներ` = "buildings") rather than a
  hardcoded list of numbered-street districts — see
  `address_grammar.py`'s module docstring for the detection rule and
  its residual limitation.
- **Marz names are stored in inflected/genitive Armenian form**
  (`Արագածոտնի`, `Սյունիքի`, `Լոռու`) rather than canonical/nominative
  form (`Արագածոտն`, `Սյունիք`, `Լոռի`), consistently across both
  parsers. Not a bug, but it will need normalizing before matching
  against a canonical marz list — deliberately deferred rather than
  guessed at now; noted here so it isn't rediscovered during the
  matching-layer work.

- **Sub-numbered range endpoints** (`67-80/2`): stored exactly as parsed
  (`sub=None` when a side has no sub-number — not synthesized). The
  "implicit `/1` floor" interpretation from `outage-data-patterns-v2.md`
  §4 is a **matching-time** rule to apply later, not a parse-time one —
  parsing stays faithful to the source.
- **Parity scope:** a parity word (`զույգ`/`կենտ`) found together with a
  number in the same comma-item applies to that item only. A parity word
  found only once, trailing a whole run of bare-number items (e.g. `47,
  47/1, 49 կենտ համարի`), is **not** retroactively applied to the earlier
  items in v1 — real example found, but resolving it needs clause-level
  lookahead not built yet. Flagged for revisit.
- **Renamed-street annotation** (V-10): `X/Y ...` where `/` appears
  before any digit in the item is treated as "current name / old name" —
  everything from `/` onward is dropped, keeping only the name before
  it. Confirmed real case: `Արաբկիր 45` is the old name of `Հ. Մալյան`
  street.
- **V-9 lane/dead-end numbers** (`Կ.Ուլնեցու 1 Նրբ.`) currently parse as
  an ordinary `street_range` (street="Կ.Ուլնեցու", low=high=1) — the lane
  number gets stored as if it were a house number. Structurally
  harmless (doesn't crash, doesn't misfile under the wrong street), but
  semantically imprecise; noted rather than solved, low frequency.
  Same "revisit later" spirit as the other simplifications on this list.
- **ENA planned qualifier scope** (`մասnaki` applying to one vs. several
  comma items): not actually exercised in v1 since ENA's address text
  isn't decomposed at all (§4) — documented here as the rule to use
  *when* that parser is built: apply to the immediately preceding item
  only, never assume it back-propagates across a comma.

## 8. Test results (against real data)

50 tests, all passing, run against every distinct real sample in the
uploaded db (not synthetic fixtures):

- **Veolia — all 40 distinct posts:** every post reaches at least
  `parse_status="partial"`; all 40 reach `"ok"` (headline region + date +
  time + address all extracted cleanly), including the two-district
  `և`-join, the missing-`-ում`-suffix case, the lowercase-district case,
  and the source-side run-on-word typo. 195 locations parsed across
  those posts: 48.7% `whole_street`, 34.9% `street_range`, 12.3%
  `street_number_range`, 4.1% `whole_area`, **0% `unparsed`**.
  `street_number_range` (numbered-street areas like Նոր Արեշ/Վարդաշեն/
  Մուշական — see §7) was previously silently folded into `street_range`
  as a house-number range; fixed after review, see §7.
- **ENA planned — both distinct real texts (rows 2 and 18):** 99 and 113
  announcements respectively, **100% `parse_status="ok"`** — every
  region/time chunk across both confirmed and preliminary day-blocks
  extracted cleanly, including nested locality sub-headings correctly
  left untouched inside `raw_address_text` and business-name-only
  entries (P-3) preserved verbatim rather than mangled.

Not yet run against a live fetch — same caveat as Phase 0.5's README:
this sandbox can't reach `ena.am` or `t.me`, so this is validated
against the historical data in the uploaded db, not a fresh live pull.

## 9. What's still not built (next step)

Per the agreed two-step split, this covers parsing only. Still to do,
once this is reviewed:

- `processing/models.py` — the actual Django models for
  `OutageAnnouncement`/`OutageLocation`, migration.
- `process_raw_content` management command (or similar) tying
  `RawContent.processed` to the parsers above, using the idempotency
  keys from §6, and setting `last_seen_at` on repeat matches.
- Localizing `starts_at`/`ends_at` to `Asia/Yerevan` (parsers currently
  return naive datetimes; Django's `USE_TZ=True` setting means the
  processing layer needs to attach the zone explicitly, not the parser).
