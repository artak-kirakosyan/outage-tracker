"""
Parses one Veolia Telegram post (see outage-data-patterns-v2.md section
2) into a structured announcement + its list of ParsedLocation rows.

Scope note: every real post seen so far (40/40) is an emergency
announcement — no planned-outage wording has ever been observed on this
channel. This parser unconditionally sets outage_type="emergency" on
every return path, including "partial"/"failed" ones — it does not
actually detect planned-outage wording. If a planned post ever appears
with a headline that doesn't say "Վթարային" but a body that still
happens to match the generic time/address template below, it would be
recorded as "emergency" with parse_status="partial" rather than being
caught. Not fixed here since outage_type accuracy isn't load-bearing at
this stage (nothing downstream reads it yet) — noted so it isn't
assumed to be safer than it is once that changes.
"""
import dataclasses
import datetime as dt
import re

from processing import normalize
from processing.address_grammar import ParsedLocation, parse_address_list
from processing.armenian_dates import MONTHS_GENITIVE as _MONTHS

_HEADLINE_RE = re.compile(
    r"^Վթարային\s+ջրանջատում\s+(?P<location>.+?)\s+(?P<month>\S+)\s+(?P<day>\d{1,2})-ին\s*$",
    re.IGNORECASE,
)

_BODY_RE = re.compile(
    r"ս\.թ\s+(?P<month>\S+)\s+(?P<day>\d{1,2})-ին\s+ժամը\s+"
    r"(?P<start_h>\d{1,2}):(?P<start_m>\d{2})\s*-\s*(?P<end_h>\d{1,2}):(?P<end_m>\d{2})-?ն?\s+"
    # \s* (not \s+) before ջրամատակարարումը: real source text has at
    # least one confirmed instance running the last word straight into
    # it with no space at all ("...Շենքերիջրամատակարարումը").
    r"կդադարեցվի\s+(?P<addr>.+?)\s*ջրամատակարարումը",
    re.IGNORECASE,
)

_YEREVAN_RE = re.compile(r"^Երևանի\s+(?P<districts>.+?)\s+վարչական\s+շրջան(?:ներ)?ում$", re.IGNORECASE)
_MARZ_SETTLEMENT_RE = re.compile(r"^(?P<marz>.+?)\s+մարզի\s*(?P<settlement>.*)$", re.IGNORECASE)
_MARZ_ONLY_RE = re.compile(r"^(?P<marz>.+?)\s+մարզում$", re.IGNORECASE)
_SETTLEMENT_SUFFIX_RE = re.compile(r"\s*(գյուղում|քաղաքում|գյուղի|քաղաքի)$", re.IGNORECASE)


@dataclasses.dataclass
class VeoliaAnnouncement:
    outage_type: str
    marz: str | None
    district_or_city: str | None
    starts_at: dt.datetime | None
    ends_at: dt.datetime | None
    raw_heading_text: str
    raw_address_text: str
    locations: list[ParsedLocation]
    parse_status: str  # "ok" | "partial" | "failed"


def _parse_headline_location(location_text: str) -> tuple[str | None, str | None]:
    """Returns (marz_or_'Երևան', district_or_settlement)."""
    text = location_text.strip()

    m = _YEREVAN_RE.match(text)
    if m:
        districts = [d.strip() for d in re.split(r"\s+և\s+", m.group("districts"))]
        return "Երևան", ", ".join(districts)

    m = _MARZ_SETTLEMENT_RE.match(text)
    if m:
        settlement = _SETTLEMENT_SUFFIX_RE.sub("", m.group("settlement")).strip()
        return m.group("marz").strip(), (settlement or None)

    m = _MARZ_ONLY_RE.match(text)
    if m:
        return m.group("marz").strip(), None

    return None, (text or None)


def parse_post(raw_text: str, *, year: int) -> VeoliaAnnouncement:
    """
    raw_text: the post's full text as scraped (headline line, blank
    line(s), body paragraph, closing boilerplate) — NOT yet normalized.
    year: the calendar year to attach to the day/month found in the
    post, since Veolia never states it. Caller should pass the year of
    the RawContent fetch (or roll over at a Dec/Jan boundary if needed
    — not handled here).
    """
    lines = [normalize.normalize_text(l) for l in raw_text.split("\n")]
    lines = [l for l in lines if l]
    if not lines:
        return VeoliaAnnouncement("emergency", None, None, None, None, "", "", [], "failed")

    heading_line = lines[0]
    body_text = " ".join(lines[1:])

    marz = district_or_city = None
    headline_match = _HEADLINE_RE.match(heading_line)
    if headline_match:
        marz, district_or_city = _parse_headline_location(headline_match.group("location"))

    body_match = _BODY_RE.search(body_text)
    if not body_match:
        return VeoliaAnnouncement(
            "emergency", marz, district_or_city, None, None, heading_line, "", [], "failed"
        )

    month = _MONTHS.get(body_match.group("month").lower())
    day = int(body_match.group("day"))
    starts_at = ends_at = None
    if month:
        starts_at = dt.datetime(year, month, day, int(body_match.group("start_h")), int(body_match.group("start_m")))
        ends_at = dt.datetime(year, month, day, int(body_match.group("end_h")), int(body_match.group("end_m")))
        if ends_at <= starts_at:
            ends_at += dt.timedelta(days=1)  # crosses midnight, e.g. 10:00-00:00 / 09:00-01:00

    raw_address_text = body_match.group("addr").strip()
    locations = parse_address_list(raw_address_text)

    parse_status = "ok"
    if not headline_match or marz is None or month is None:
        parse_status = "partial"

    return VeoliaAnnouncement(
        outage_type="emergency",
        marz=marz,
        district_or_city=district_or_city,
        starts_at=starts_at,
        ends_at=ends_at,
        raw_heading_text=heading_line,
        raw_address_text=raw_address_text,
        locations=locations,
        parse_status=parse_status,
    )
