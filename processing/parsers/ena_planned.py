"""
Parses ENA's "Պլանային անջատումներ" (planned outages) prose section.

Deliberately shallow, per the v1 scope decision: this extracts date,
top-level region (marz, or Yerevan + district), and time window into
structured fields, but the address portion is kept as one verbatim
`raw_address_text` string — it is NOT decomposed into per-street/range
OutageLocation rows the way Veolia's parser does. Reasons, confirmed
against real data (see the processing plan doc for the full writeup):

  - The address text nests a second heading level (locality names like
    "Զոլաքար գյուղ՝", "Ջերմուկ քաղաք՝") *inside* a single time-slot's
    text, freely mixed with plain street lists, business/institution
    names, numbered-street ranges, and multi-word qualifiers
    (մասնակի/ամբողջությամբ/ոչ բնակիչ-բաժանորդներ) whose scope is often
    ambiguous over multiple list items. Getting real matching precision
    out of this would need meaningfully more grammar than Veolia's flat
    comma-list, for a source that (per the top-level plan) is disabled
    less often / less real-time-critical than Veolia's emergency feed.
  - This is a deliberate v1 trade-off, not a limitation of the grammar
    itself — a full parser can be built later against raw_address_text,
    which is preserved verbatim specifically so nothing is lost.

Structural discriminator used here, confirmed against real data: a
TOP-LEVEL region heading always contains "մարզ" or "վարչական շրջան"
(Yerevan-district). Any other "<name>՝"-style heading found inside an
address block is a locality-level sub-heading, not a region change, and
is deliberately left untouched inside raw_address_text.

Two day-block shapes exist on the same page, confirmed real (see plan
doc): "confirmed" blocks (separated by a literal run of asterisks, each
opening with the full company-name sentence) and a trailing
"Պլանային անջատումների մասին նախնական տեղեկատվություն" ("preliminary
information") section containing further date-only sub-blocks with a
shorter opening sentence, not separated by asterisks. Both shapes are
handled by the same opening-sentence regex (company-name prefix is
optional) and flagged via `is_preliminary`.
"""
import dataclasses
import datetime as dt
import re

from processing.armenian_dates import MONTHS_GENITIVE

_ASTERISK_DIVIDER_RE = re.compile(r"\*{5,}")
_PRELIMINARY_HEADER_RE = re.compile(r"Պլանային\s+անջատումների\s+մասին\s+նախնական\s+տեղեկատվություն", re.IGNORECASE)
_FOOTER_RE = re.compile(r"Սպառած\s+էլեկտրաէներգիայի.*$", re.IGNORECASE | re.DOTALL)

_OPENING_SENTENCE_RE = re.compile(
    r"(?:«Հայաստանի\s+էլեկտրական\s+ցանցեր».*?տեղեկացնում\s+է,\s*որ\s+)?"
    r"(?P<month>\S+)\s+(?P<day>\d{1,2})-ին\s+պլանային\s+նորոգման\s+աշխատանքներ\s+"
    r"իրականացնելու\s+նպատակով\s+ժամանակավորապես\s+կդադարեցվի\s+հետևյալ\s+հասցեների\s+"
    r"էլեկտրամատակարարումը[՝`]?",
    re.IGNORECASE | re.DOTALL,
)

_DATE_HEADING_SPLIT_RE = re.compile(
    r"(?=(?:" + "|".join(MONTHS_GENITIVE) + r")\s+\d{1,2}-ին\s+պլանային)", re.IGNORECASE
)

_REGION_HEADING_RE = re.compile(
    r"(?P<region>(?:Երևանի\s+[Ա-ֆԱ-Ֆ][Ա-ֆԱ-Ֆ\-\s]*?\s+վարչական\s+շրջան|[Ա-ֆԱ-Ֆ][Ա-ֆԱ-Ֆ\-\s]*?\s+մարզ)ի?)\s*[՝`]",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")


@dataclasses.dataclass
class EnaPlannedAnnouncement:
    outage_type: str  # always "planned"
    is_preliminary: bool
    marz_or_yerevan: str | None
    district: str | None  # only set for Yerevan
    date: dt.date | None
    starts_at: dt.datetime | None
    ends_at: dt.datetime | None
    raw_heading_text: str
    raw_address_text: str
    parse_status: str  # "ok" | "partial" | "failed"


def _split_region(region_text: str) -> tuple[str | None, str | None]:
    text = region_text.strip()
    m = re.match(r"^Երևանի\s+(?P<district>.+?)\s+վարչական\s+շրջանի?$", text, re.IGNORECASE)
    if m:
        return "Երևան", m.group("district").strip()
    m = re.match(r"^(?P<marz>.+?)\s+մարզի?$", text, re.IGNORECASE)
    if m:
        return m.group("marz").strip(), None
    return None, None


def _parse_day_block(block_text: str, *, is_preliminary: bool, year: int) -> list[EnaPlannedAnnouncement]:
    block_text = _FOOTER_RE.sub("", block_text).strip()

    opening = _OPENING_SENTENCE_RE.search(block_text)
    if not opening:
        # Can't even find the date/opening sentence — nothing usable to
        # extract. Surface it as a single failed record rather than
        # silently dropping the block's content.
        return [
            EnaPlannedAnnouncement(
                "planned", is_preliminary, None, None, None, None, None,
                raw_heading_text=block_text[:200], raw_address_text=block_text, parse_status="failed",
            )
        ]

    month = MONTHS_GENITIVE.get(opening.group("month").lower())
    day = int(opening.group("day"))
    date = dt.date(year, month, day) if month else None
    body = block_text[opening.end():].strip()

    region_matches = list(_REGION_HEADING_RE.finditer(body))
    if not region_matches:
        return [
            EnaPlannedAnnouncement(
                "planned", is_preliminary, None, None, date, None, None,
                raw_heading_text=opening.group(0), raw_address_text=body, parse_status="partial",
            )
        ]

    results: list[EnaPlannedAnnouncement] = []
    for i, region_match in enumerate(region_matches):
        marz_or_yerevan, district = _split_region(region_match.group("region"))
        region_body_start = region_match.end()
        region_body_end = region_matches[i + 1].start() if i + 1 < len(region_matches) else len(body)
        region_body = body[region_body_start:region_body_end]

        time_matches = list(_TIME_RE.finditer(region_body))
        if not time_matches:
            results.append(
                EnaPlannedAnnouncement(
                    "planned", is_preliminary, marz_or_yerevan, district, date, None, None,
                    raw_heading_text=region_match.group("region"),
                    raw_address_text=region_body.strip(),
                    parse_status="partial",
                )
            )
            continue

        for j, time_match in enumerate(time_matches):
            addr_start = time_match.end()
            addr_end = time_matches[j + 1].start() if j + 1 < len(time_matches) else len(region_body)
            raw_address_text = region_body[addr_start:addr_end].strip(" ,;")

            starts_at = dt.datetime(
                date.year, date.month, date.day, int(time_match.group(1)), int(time_match.group(2))
            ) if date else None
            ends_at = dt.datetime(
                date.year, date.month, date.day, int(time_match.group(3)), int(time_match.group(4))
            ) if date else None
            if starts_at and ends_at and ends_at <= starts_at:
                ends_at += dt.timedelta(days=1)

            results.append(
                EnaPlannedAnnouncement(
                    outage_type="planned",
                    is_preliminary=is_preliminary,
                    marz_or_yerevan=marz_or_yerevan,
                    district=district,
                    date=date,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    raw_heading_text=region_match.group("region"),
                    raw_address_text=raw_address_text,
                    parse_status="ok" if raw_address_text else "partial",
                )
            )

    return results


def parse_planned_section(text: str, *, year: int) -> list[EnaPlannedAnnouncement]:
    """
    text: the full, already-normalized text of the "attenbody" span
    (see the ingestion HTML — id contains 'attenbody'), i.e. everything
    under the "Պլանային անջատումներ" heading. Newlines are collapsed
    here since ENA's own <br> placement wraps headings arbitrarily
    mid-phrase and carries no semantic meaning.
    """
    flat = re.sub(r"\s+", " ", text).strip()

    segments = [s.strip() for s in _ASTERISK_DIVIDER_RE.split(flat) if s.strip()]

    results: list[EnaPlannedAnnouncement] = []
    for segment in segments:
        if _PRELIMINARY_HEADER_RE.search(segment):
            sub_segments = _DATE_HEADING_SPLIT_RE.split(segment)
            for sub in sub_segments:
                sub = sub.strip()
                if not sub or _PRELIMINARY_HEADER_RE.match(sub):
                    continue
                results.extend(_parse_day_block(sub, is_preliminary=True, year=year))
        else:
            results.extend(_parse_day_block(segment, is_preliminary=False, year=year))

    return results
