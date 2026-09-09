# Outage Data Patterns

Full pattern catalog for both providers, built from the real, uploaded
`db.sqlite3` (35 ENA rows, 113 Veolia-Telegram rows, both fetched
2026-09-04 → 2026-09-06). Every example is real, copied verbatim from
`RawContent.content`. §1–3 catalog every distinct pattern seen per
provider, with real examples. §4 consolidates the parsing decisions and
assumptions this data review settled on — that's the part that drove the
`OutageEvent` schema (see §7). §5 lists what's still genuinely unknown.

---

## 1. ENA — two structurally different sections on one page

### 1.1 Emergency & preventive table (`Վթարային և կանխարգելիչ անջատումներ`)

Flat HTML `<table id="...vtarayin">`. Columns: `Անջատման ամսաթիվ`
(termination datetime, `DD.MM.YYYY HH:MM`) | `Հասցե` (address) |
`Բաժանորդների քանակ` (subscriber count). One row = one location, never
bundled.

This is a long-lived running log, not "current outages only" — the
oldest row across the 35 snapshots is dated 2025-02-13, the newest
matches the fetch date, and it appears to only ever grow: 12,000
distinct (timestamp, address) pairs total. A Phase 1 processor needs
its own watermark against `Անջատման ամսաթիվ`, independent of the
row-level `processed` flag, since one page fetch can contain thousands
of entries, the vast majority already seen in a prior fetch.

**Emergency vs. preventive classification** — the table's own heading
blends both, with no per-row field distinguishing them. Rule for
resolving this is in §4.

**Marz/city** — this table's addresses don't reliably carry marz/city;
decision on scoping this out of Phase 1 is in §4. Documenting the real
address patterns below regardless, since they're still needed for
street/range matching even without marz.

#### Address (`Հասցե`) patterns

Every value starts with a settlement-type prefix: `ք.` (city) or `գ.`
(village). From there, by real frequency across the 10,828 distinct
address strings:

**E-1 — Whole settlement, no street** (2,089 of 10,828)
```
գ.ԱԼՎԱՆՔ
ք.ԱՐԱՐԱՏ
```
Sub-variant: settlement + bare number, no street name at all —
`գ.ԱԼՎԱՆՔ, 1` / `, 2` / `, 3`... — some villages appear to number
houses/plots sequentially with no named streets.

**E-2 — Settlement + street, no house number** (whole street)
```
ք.ՍԵՎԱՆ, ԲԱՐԵԿԱՄՈՒԹՅԱՆ փող.
```

**E-3 — Settlement + street + single house number**
```
ք.ՍԵՎԱՆ, ԵԼԵՆՈՎԿԱ փող. 02
```
249 of 10,828 addresses have a zero-padded house number (`01` through
`09`). Parse as an integer for range logic; keep the original
zero-padded string for display.

**E-4 — Settlement + street + house w/ sub-number**
```
գ.ԱՎՇԱՐ, ԽՈՐԵՆԱՑՈՒ փող. 2/1
```
The `main/sub` format the top-level plan anticipated.

**E-5 — Settlement + street + lane + house** (1,055 of 10,828 —
surprisingly common)
```
գ.ԱԳԱՐԱԿԱՎԱՆ (ԹԱԼԻՆԻ շրջ.), 1 փող. 10 նրբ. 9
```
`նրբ.` = `նրբանցք` (lane/alley) — a 3-level street→lane→house
hierarchy, not just street→house.

**E-6 — Settlement + numbered quarter + street + house**
```
գ.ԱՅԳԵԿ, ՄՈՒՇԱՎԱՆ 6 թաղ. 6 փող. 6
```
`թաղ.` = `թաղամասը` (quarter/microdistrict), itself numbered, sitting
between settlement and street.

**E-7 — Hyphen used two different ways**

Genuine ascending ranges are real:
```
գ.ՁՈՐԱՂԲՅՈՒՐ, 1-21
գ.ՓԱՐԱՔԱՐ, 6-8
գ.ՄԵՐՁԱՎԱՆ, 1 փող. 17-19
```

But `-` is also used, inconsistently, as an alternative to `/` for
sub-numbers — **this is not a range at all**:
```
գ.ԶՈՎՈՒՆԻ, 2 փող. 17-1        → same address as 17/1, a single house
գ.ՔԱՆԱՔԵՌԱՎԱՆ, 11 փող. 38-1   → same address as 38/1
```
Discriminator: if the second number is smaller than the first, it's the
sub-number notation, not a range — ENA just picked a bad delimiter for
it, nothing to fix on our end, only detect.

**E-8 — Explicit comma-separated list, sub-numbers listed individually**
```
ք.ԵՐԵՎԱՆ, ՌՈՒԲԻՆՅԱՆՑ փող. 17,17/1,19
```
Confirms the top-level plan's existing rule directly: `17`, `17/1`, and
`19` are each listed separately, not folded into a range.

A denser real example, with the abbreviation partly identified:
```
գ.ՁՈՐԱՂԲՅՈՒՐ, 2Ա/Ձ 51,12     → "Ա/Ձ" = ԱՁ = անհատ ձեռնարկատեր
                                 (individual entrepreneur)
գ.ՁՈՐԱՂԲՅՈՒՐ, 2զ/ծ,37թ.4      → "զ/ծ" still unknown — see §5
```

**E-9 — Parenthetical district disambiguator**
```
գ.ԱԳԱՐԱԿԱՎԱՆ (ԹԱԼԻՆԻ շրջ.)
```
20 distinct qualifiers seen, format `([name]ի շրջ.)` — Talin, Abovyan,
Hrazdan, Sisian, Meghri, Ashtarak, and 14 others. Capitalization is
inconsistent (`ԱՇՈՑՔԻ շրջ.` and `ԱՇՈՑՔԻ ՇՐՋ.` both occur for the same
place) — normalize case before matching. Real, useful disambiguation
signal on ~20 known-ambiguous villages, but present too inconsistently
across the table as a whole to build marz/city matching on top of —
doesn't change the "out of scope for Phase 1" call in §4.

**Confirmed absent from this table:** even/odd wording, `մասնակի`
(partial) — both real, but only ever seen in the planned-outage block
below.

### 1.2 Planned outages (`Պլանային անջատումներ`) — free-form prose

Completely different shape from the emergency table — prose, not a
table.

- A page can bundle **multiple day-blocks**, each opening with the same
  boilerplate sentence naming its date and closing with a phone-number/
  safety footer, separated by a literal line of asterisks
  (`****************`). 3 day-blocks were captured across the 35
  snapshots (Sep 4, 7, 8).
- Within a day-block: `[Region]՝` → one or more `[HH:MM–HH:MM]`
  sub-headings → a semicolon/comma-separated address list for that
  region+time.
- Regions seen: Yerevan admin districts (Ajapnyak, Avan, Arabkir,
  Davtashen, Erebuni, Malatia-Sebastia, Nor Nork/Marash, Nubarashen,
  Shengavit, Kentron, Kanaker-Zeytun) and marzes (Aragatsotn, Ararat,
  Gegharkunik, Kotayk, Lori, Shirak, Syunik, Tavush, Vayots Dzor). A
  marz section can drop straight to a named locality with its own
  sub-heading, e.g. `Ավան՝` inside a wider Kotayk-marz block.

**P-1 — Whole street(s), explicitly `մասնակի` ("partially")** — 65
occurrences across the 3 day-blocks
```
Բատիկյան, Մալաթիա, Վանթյան փողոցներ մասնակի
```
Counterpart word also real: `ամբողջությամբ` ("entirely") — the two can
appear side by side in one list:
```
11-րդ փողոցն ամբողջությամբ, 2-րդ փողոց մասնակի
```

**P-2 — Whole settlement, `մասնակի`**
```
Այգեզարդ գյուղ մասնակի
Խնձորուտ գյուղ մասնակի
```

**P-3 — Named entity, not an address at all**
```
«Խճաքար-Մուսա», «Ծիրան Մարկետ», «Ունիվերսալ Հոսպիտալ Պրոդակտ» ՍՊԸ-ներ
թիվ 148 մանկապարտեզ, թիվ 168 դպրոց
ԱՁ Կ. Պողոսյան
Սեփականատեր՝ Վ. Մանուկյան
```
Businesses (`ՍՊԸ` = LLC), numbered public institutions (kindergarten,
school), individual entrepreneurs (`ԱՁ`), named property owners. None
of these will ever match a residential street address — ignored, not
stored as matchable `OutageEvent` locations, per §4.

**P-4 — Range with sub-numbered endpoints**
```
Վերին Անտառային փողոց 124/1–138/6, 128/2, 136/11...
```
A range whose *both* endpoints carry sub-numbers, mixed with
individually-listed sub-numbered buildings right after it in the same
list. Same notation issue as Veolia's V-6 pattern below — matching rule
is in §4.

**P-5 — Boilerplate qualifier, strip don't parse**
```
և հարակից ոչ բնակիչ-բաժանորդներ
```
"and adjacent non-resident subscribers" — trails almost every entry;
not a location, a qualifier on the preceding one.

---

## 2. Veolia — Telegram channel

40 distinct real posts, Sep 2–5. All 40 are emergency
(`Վթարային ջրանջատում`) — no planned-outage post appears anywhere in
this data, so this source is treated as always `emergency` (§4).

### 2.1 Headline — real variants observed

`Վթարային ջրանջատում [location] [date]-ին`, where `[location]` isn't
one fixed shape:

| Shape | Real example |
|---|---|
| marz + village | `Արմավիրի մարզի Լուկաշին գյուղում` |
| marz + city | `Սյունիքի մարզի Գորիս քաղաքում` |
| marz + city, missing the `-ում` suffix (grammar inconsistency, seen once) | `Լոռու մարզի Ստեփանավան` |
| Yerevan + one district | `Երևանի Արաբկիր վարչական շրջանում` |
| Yerevan + **two** districts, joined by "և", pluralized | `Երևանի Արաբկիր և Քանաքեռ Զեյթուն վարչական շրջաններում` |
| marz alone, no city/village (a genuinely marz-wide post) | `Կոտայքի մարզում` |
| Capitalization inconsistent (seen once) | `Երևանի էրեբունի վարչական շրջանում` |

Marz/city is always resolvable from the headline — no open issue here,
unlike ENA's emergency table.

### 2.2 Body — confirmed structure

```
«Վեոլիա Ջուր» ընկերությունը տեղեկացնում է իր հաճախորդներին և
սպառողներին, որ վթարային աշխատանքներով պայմանավորված ս.թ [date]-ին
ժամը [start]-[end]-ն կդադարեցվի [ADDRESS LIST] ջրամատակարարումը:
```
followed by a closing sentence present on **every real post** in this
dataset:
```
Ընկերությունը հայցում է սպառողների ներողամտությունը պատճառված
անհանգստության և կանխավ շնորհակալություն հայտնում ըմբռնման համար:
```
**Action item:** `ingestion/tests/fixtures/veolia_telegram_sample.html`
is missing this closing sentence — update the fixture so it matches
real posts.

Time-range notes:
- Can cross midnight: `ժամը 10:00-00:00-ն`, `ժամը 09:00-01:00` (runs
  into the next calendar day).
- Trailing grammatical `-ն` is sometimes present, sometimes not —
  cosmetic, strip it.

### 2.3 Address-list patterns

Real posts routinely bundle a dozen-plus streets in one entry, far
denser than a single-location announcement.

**V-1 — Whole settlement**
```
Կոռնիձոր գյուղի
Շահումյան գյուղի
```

**V-2 — Whole district/neighborhood**
```
ք.Կապան Ձորքի Թաղամասի
```

**V-3 — Bare street name, no numbers (whole street)**
```
Ազատամարտիկների Պող., Ռոստովյան, Նոր Արեշ 12, 14 փողոցների
```
`Պող.` = `պողոտա` (avenue) — a third way-type word alongside street
(`փող.`) and highway (`խճ.`).

**V-4 — Street + simple range**
```
Վարդաշեն 1-12 փողոցների, Մուշական 1-11 փողոցների
```
Reads as *street numbers* 1–12, not house numbers — some Yerevan
outlying districts number their streets rather than name them.

**V-5 — Street + range with a lettered upper bound**
```
Գյուլբենկյանի 1-29Ա Շենքերի
```

**V-6 — Street + range with a sub-numbered bound on one or both ends**
```
Ավետ Ավետիսյանի 67-80/2 շենքերի
Կ. Ուլնեցու 1-62/3 շենքերի
```
More complex than the top-level plan's original `20-40` example — a
range endpoint can itself carry a sub-number unrelated to the other
end. Matching rule for this shape is in §4.

**V-7 — One street, a dozen+ comma-separated sub-ranges/singles** (the
densest real pattern seen)
```
Ազատության 1-2, 2/1-2/6, 4-4/2, 4Ա, 6-6/6, 8-8/4, 10, 10/7,
12-12/8, 14/2-18, 20, 24-24/9, 26-26/9
```
One street name governing 13 comma-separated items — some single
numbers, some simple ranges, some sub-numbered ranges — all under one
heading.

**V-8 — Parity word, confirmed real**
```
Կ.Ուլնեցու 58-58/4 զույգ Շենքերի          ← "even" (զույգ)
Խորենացի 47, 47/1, 49 կենտ համարի շենքերի  ← "odd-numbered" (կենտ համարի)
```
The second example applies "odd" as a qualifier over an explicit list,
not a range. How parity combines with a sub-numbered range (like V-6)
is decided in §4.

**V-9 — Lane/dead-end sub-identifiers off one named street**
```
Կ.Ուլնեցու 1 Նրբ., Կ.Ուլնեցու 1 փակ., Կ.Ուլնեցու 2 Նրբ., Կ.Ուլնեցու 2 փակ.
```
Same street, several numbered lanes (`Նրբ.`) and dead-ends (`փակ.`),
each listed as its own item.

**V-10 — Renamed-street annotation, resolved**
```
Հ. Մալյան/Արաբկիր 45 փող.
```
`Արաբկիր 45` is the confirmed old name of what's now `Հ. Մալյան`
street — a "current name / old name" annotation, not an intersection
or a second address. Parsing rule: everything from `/` onward is
dropped, keeping only the name before it — see §4.

**Noise, not a real pattern:** `Ն.Սուրենյանի /Ն. Սուրենյանի` — reads
like an accidental duplicate in Veolia's own source text; the parser
should tolerate this kind of glitch rather than choke on it.

### 2.4 Cross-post note

The dense Arabkir/Kanaker-Zeytun street list from V-7 above was posted
**verbatim on two different dates** (Sep 3 and Sep 4) with different
time windows — Veolia re-announces a multi-day outage separately each
day rather than posting one announcement with a date range. For the
structured layer: treat each post as its own `OutageEvent`, don't try
to merge across days, but expect near-duplicate address lists on
consecutive days for the same underlying work.

---

## 3. Veolia — website (`veolia_web`)

All 8 rows in this db are `error`. Nothing to analyze — consistent with
it being disabled by default per the updated top-level plan. If an
older db exists from before it was disabled, that'd be worth a look for
comparison against the Telegram channel's phrasing; otherwise this stays
a documented-but-currently-unused code path.

---

## 4. Decisions

The calls this data review settled on. Several are **our own
assumptions, not provider-confirmed** — flagged explicitly where that's
the case, since they'll need revisiting if ENA/Veolia ever clarify.

**Outage type**
- ENA `Պլանային` section → `planned`.
- ENA `Վթարային և կանխարգելիչ` table → defaults to `preventive` for
  now (Phase 1 v1). A later pass can reclassify a row to `emergency` by
  comparing its `Անջատման ամսաթիվ` to processing time — if that
  datetime is still in the future, it's an active/urgent entry
  (`emergency`); if it's already past, it's historical (`preventive`).
  Not built in v1, just the decided rule for when it is.
- Veolia Telegram → always `emergency` (no planned wording ever
  observed; revisit if that changes).

**Geography (marz/city)**
- ENA emergency table: out of scope for Phase 1. Too inconsistent to
  reliably resolve marz/city from this table alone (only the settlement
  name, plus an inconsistent parenthetical district hint on ~20
  known-ambiguous villages). `OutageEvent`s from this source carry no
  marz field in v1 — a documented limitation, not a bug.
- ENA planned block: resolved from the region heading, no issue.
- Veolia Telegram: resolved from the headline, no issue.

**Range delimiter**: always `-` (occasionally `–`), confirmed both
providers, no other delimiter exists.

**Even/odd parity**: ENA — assumed absent, not building parity handling
for ENA in v1 (never observed across 35 snapshots). Veolia — confirmed
real, must be handled.

**Hyphen as a sub-number alternative (ENA, confirmed)**: `17-1`, `38-1`
etc. are not ranges — ENA uses `-` inconsistently as an alternative to
`/` for sub-numbers. Detected when the second number is smaller than
the first; treated as a single sub-numbered address (`17/1`), not a
range.

**⚠️ Sub-numbered range endpoints — our own rule, not provider-confirmed:**
When a range has a sub-number on only one end (e.g. `67-80/2`), assume
the bare end implicitly means `/1`: treat the range as spanning
`67/1`–`80/2`. Matching:
- main number strictly between the two bounds → matches regardless of
  sub-number
- main number equals a bound that has a sub-number → matches only if
  the address's own sub-number falls within that bound's sub-number
  (using `/1` as the implicit floor on whichever end lacks one)

When parity co-occurs with a sub-numbered range (e.g. `58-58/4 զույգ`),
parity filters the **main number only** (58), not the sub-number.
Not yet observed, but worth watching for in future data: parity might
also apply to the sub-number itself — possibly phrased something like
`կենտ կոտորակներ` ("odd fractions"). No example seen yet; flagging so
it's recognized if it shows up.

This whole rule is a guess pending outreach to ENA/Veolia — document it
as an assumption in the parser code, not as confirmed provider behavior.

**Multiple locations per entry**: confirmed common in ENA's planned
block and every Veolia Telegram post; ENA's emergency table stays
strictly one location per row.

**Non-address entities** (named businesses, institutions, individual
owners — ENA planned block only): ignored for Phase 1, not stored as
matchable `OutageEvent` locations. (`ԱՁ` / `Ա/Ձ` identified as
"individual entrepreneur" — doesn't change the decision to ignore
these.)

**Renamed-street annotation (V-10), resolved**: `X/Y ...` where `/`
appears before any digit in the item is a "current name / old name"
annotation, not an intersection or second address — everything from
`/` onward is dropped, keeping only the name before it. Confirmed:
`Արաբկիր 45` is the old name of `Հ. Մալյան` street.

---

## 5. Still open

1. `զ/ծ` abbreviation (ENA, handful of Ձորաղբյուր addresses) — still
   unknown. Only appears in ENA's emergency table, which is out of
   Phase 1 v1 scope, so this doesn't block anything currently being
   built.

Neither this nor any other narrow, low-frequency edge case above blocks
schema design — each can be stored as raw/unparsed text and revisited
later.

## 6. Action items

1. Update `ingestion/tests/fixtures/veolia_telegram_sample.html` to
   include the closing boilerplate sentence every real post has. Still
   outstanding.
2. Whenever convenient, reach out to ENA/Veolia to confirm or correct
   the sub-numbered-range assumption in §4 — it's currently our best
   guess, not their documented behavior.

## 7. Next step — Done

The `OutageAnnouncement`/`OutageLocation` schema and per-pattern
extraction rules were sketched and built against the decisions in §4.
See `docs/phase-1-processing-plan.md` for the schema, the fidelity
split (Veolia fully decomposed, ENA planned kept shallow), and current
implementation status.
