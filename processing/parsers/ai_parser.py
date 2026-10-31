"""
AI-driven parser for Armenian utility outage announcements using Gemini.

Extracts structured outage entities and decomposes address lists into
ParsedLocation objects for ENA (electricity) and Veolia (water),
handling free-form formatting variations, typos, punctuation differences,
and language morphology without fragile regex rules.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
import threading
import time
from typing import Literal

from django.conf import settings
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from processing.address_grammar import LocationKind, Parity, ParsedLocation, Qualifier
from processing.parsers.ena_planned import EnaPlannedAnnouncement, _ASTERISK_DIVIDER_RE, _PRELIMINARY_HEADER_RE, _DATE_HEADING_SPLIT_RE
from processing.parsers.veolia_telegram import VeoliaAnnouncement

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Schemas for Structured Output
# ---------------------------------------------------------------------------

class AILocationItem(BaseModel):
    street_name: str = Field(
        description="Armenian street or avenue name (e.g. Կոմիտասի պող., Վ.Համբարձումյան, Զավարյան փողոց, Տոլստոյի փողոց)"
    )
    building_numbers: str = Field(
        default="",
        description="Building numbers or ranges as written in the text (e.g. '1-29Ա', '20, 22', 'կենտ 1-15', '58-58/4 զույգ շենքեր'). Leave empty if whole street.",
    )
    is_whole_street: bool = Field(
        default=False,
        description="True if the entire street is affected without specific building numbers",
    )
    house_low: int | None = Field(
        default=None,
        description="Starting house number if numeric range or single house (e.g. 1 in 1-29, 20 in 20)",
    )
    house_low_sub: str | None = Field(
        default=None,
        description="Starting house sub-number suffix (e.g. '1' in '2/1' or 'Ա' in '1Ա')",
    )
    house_high: int | None = Field(
        default=None,
        description="Ending house number if numeric range or single house (e.g. 29 in 1-29, 20 in 20)",
    )
    house_high_sub: str | None = Field(
        default=None,
        description="Ending house sub-number suffix (e.g. '2' in '80/2' or 'Ա' in '29Ա')",
    )
    parity: Literal["any", "odd", "even"] = Field(
        default="any",
        description="Parity: 'odd' for կենտ, 'even' for զույգ, else 'any'",
    )
    locality: str | None = Field(
        default=None,
        description="Nested city, village, or quarter if specified (e.g. 'Զոլաքար գյուղ', 'Ջերմուկ քաղաք')",
    )
    raw_fragment: str = Field(
        default="",
        description="Verbatim raw text snippet for this street entry",
    )


class VeoliaPostSchema(BaseModel):
    outage_type: Literal["emergency", "planned"] = "emergency"
    marz: str = Field(
        description="Armenian marz name (Երևան, Կոտայք, Լոռի, Արմավիր, Արարատ, etc.)"
    )
    district_or_city: str | None = Field(
        default=None,
        description="Yerevan administrative district (e.g. Արաբկիր, Կենտրոն, Քանաքեռ-Զեյթուն) or city/settlement outside Yerevan",
    )
    starts_at_iso: str | None = Field(
        default=None,
        description="Estimated start datetime in ISO format: YYYY-MM-DDTHH:MM:SS",
    )
    ends_at_iso: str | None = Field(
        default=None,
        description="Estimated end datetime in ISO format: YYYY-MM-DDTHH:MM:SS",
    )
    raw_heading_text: str = Field(
        default="",
        description="The headline / region line from the post",
    )
    raw_address_text: str = Field(
        default="",
        description="The verbatim address list segment from the post",
    )
    locations: list[AILocationItem] = Field(default_factory=list)


class EnaSlotItem(BaseModel):
    marz_or_yerevan: str = Field(
        description="Armenian marz: Երևան, Կոտայք, Շիրակ, etc."
    )
    district: str | None = Field(
        default=None,
        description="For Yerevan: administrative district (e.g. Կենտրոն, Արաբկիր). None if outside Yerevan.",
    )
    city_or_village: str | None = Field(
        default=None,
        description="Town or village name if outside Yerevan",
    )
    starts_at_iso: str | None = Field(
        default=None,
        description="Estimated start datetime in ISO format: YYYY-MM-DDTHH:MM:SS",
    )
    ends_at_iso: str | None = Field(
        default=None,
        description="Estimated end datetime in ISO format: YYYY-MM-DDTHH:MM:SS",
    )
    raw_heading_text: str = Field(
        default="",
        description="Region and time heading text",
    )
    raw_address_text: str = Field(
        default="",
        description="Verbatim addresses for this time slot",
    )
    locations: list[AILocationItem] = Field(default_factory=list)


class EnaDayBlockSchema(BaseModel):
    date_iso: str | None = Field(
        default=None,
        description="Date of the outages in ISO format: YYYY-MM-DD",
    )
    is_preliminary: bool = Field(
        default=False,
        description="True if this is preliminary information (նախնական տեղեկատվություն)",
    )
    slots: list[EnaSlotItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Client & Generation Helpers
# ---------------------------------------------------------------------------

def get_api_key() -> str:
    key = getattr(settings, "GEMINI_API_KEY", None)
    if key is not None:
        return key
    return os.environ.get("GEMINI_API_KEY", "")


def get_genai_client() -> genai.Client | None:
    api_key = get_api_key()
    if not api_key:
        return None
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(headers={"User-Agent": "aistudio-build"}),
    )


def is_ai_parser_available() -> bool:
    if not getattr(settings, "USE_AI_PARSER", True):
        return False
    return bool(get_api_key())



_LAST_REQUEST_TIMESTAMP = 0.0
_REQUEST_LOCK = threading.Lock()


def _throttle() -> None:
    delay = getattr(settings, "GEMINI_REQUEST_DELAY_SECONDS", 0.0)
    if delay <= 0:
        return
    global _LAST_REQUEST_TIMESTAMP
    with _REQUEST_LOCK:
        now = time.time()
        elapsed = now - _LAST_REQUEST_TIMESTAMP
        if elapsed < delay:
            time.sleep(delay - elapsed)
        _LAST_REQUEST_TIMESTAMP = time.time()


def _extract_retry_delay(err: Exception, default: float = 15.0) -> float:
    details = getattr(err, "details", None)
    if isinstance(details, dict):
        for item in details.get("details", []):
            if isinstance(item, dict) and "retryDelay" in item:
                val = item["retryDelay"]
                if isinstance(val, str) and val.endswith("s"):
                    try:
                        return float(val[:-1]) + 1.0
                    except ValueError:
                        pass
    msg = str(err)
    m = re.search(r"retry in (\d+(?:\.\d+)?)s", msg, re.IGNORECASE)
    if m:
        return float(m.group(1)) + 1.0
    m2 = re.search(r"retryDelay[\'\"]?:\s*[\'\"]?(\d+)s", msg, re.IGNORECASE)
    if m2:
        return float(m2.group(1)) + 1.0
    return default


def _generate_with_fallback(
    client: genai.Client,
    contents: str,
    system_instruction: str,
    response_schema: type[BaseModel],
):
    primary_model = getattr(settings, "GEMINI_MODEL", "gemini-3.5-flash")
    fallback_model = getattr(settings, "GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")

    models_to_try = [primary_model]
    if fallback_model and fallback_model != primary_model:
        models_to_try.append(fallback_model)

    last_err: Exception | None = None
    for model_name in models_to_try:
        max_attempts = 3
        for attempt in range(max_attempts):
            _throttle()
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=response_schema,
                        system_instruction=system_instruction,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    ),
                )
                return response
            except Exception as err:
                last_err = err
                is_rate_limit = (
                    getattr(err, "code", None) == 429
                    or getattr(err, "status", None) == "RESOURCE_EXHAUSTED"
                    or "429" in str(err)
                    or "RESOURCE_EXHAUSTED" in str(err)
                )
                if is_rate_limit and attempt < max_attempts - 1:
                    raw_wait = _extract_retry_delay(err, default=15.0 * (attempt + 1))
                    # Cap at 60 s — if the API reports a multi-hour quota
                    # exhaustion we don't want to block the process; better
                    # to exhaust retries quickly, fall through to the fallback
                    # model, and ultimately let the regex parser take over.
                    wait_time = min(raw_wait, 60.0)
                    logger.warning(
                        "Gemini rate limit hit for %s (attempt %d/%d). Sleeping %.1fs before retry...",
                        model_name,
                        attempt + 1,
                        max_attempts,
                        wait_time,
                    )
                    time.sleep(wait_time)
                    continue

                logger.warning("Gemini model %s generation failed: %s", model_name, err)
                break

    if last_err is not None:
        raise last_err
    raise RuntimeError("No models configured to try")



# ---------------------------------------------------------------------------
# Location Expansion Helper
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"(\d+)(?:/(\w+))?\s*(?:-|–|—|ից\s*մինչև|ից)\s*(\d+)(?:/(\w+))?")
_SINGLE_RE = re.compile(r"(\d+)(?:/(\w+)|([Ա-Ֆա-ֆ]))?")


def parse_building_clause(bld_str: str) -> list[tuple[str, str, int | None, str | None, int | None, str | None, str]]:
    """
    Decompose a building numbers string (e.g. '21/1, 23, 25-30', '58-58/4 զույգ')
    into individual (fragment, kind, low, low_sub, high, high_sub, parity) tuples.
    """
    results = []
    parity = "any"
    if "կենտ" in bld_str or "odd" in bld_str.lower():
        parity = "odd"
    elif "զույգ" in bld_str or "even" in bld_str.lower():
        parity = "even"

    tokens = [t.strip() for t in bld_str.split(",") if t.strip()]
    if not tokens:
        return [("", "whole_street", None, None, None, None, parity)]

    for tok in tokens:
        rm = _RANGE_RE.search(tok)
        if rm:
            low = int(rm.group(1))
            low_sub = rm.group(2)
            high = int(rm.group(3))
            high_sub = rm.group(4)
            results.append((tok, "street_range", low, low_sub, high, high_sub, parity))
            continue
        sm = _SINGLE_RE.search(tok)
        if sm:
            num = int(sm.group(1))
            sub = sm.group(2) or sm.group(3)
            results.append((tok, "street_range", num, sub, num, sub, parity))
            continue
        results.append((tok, "whole_street", None, None, None, None, parity))
    return results


def ai_location_to_parsed_locations(loc: AILocationItem, default_locality: str = "") -> list[ParsedLocation]:
    """Convert an AILocationItem into one or more domain ParsedLocation objects."""
    locality = loc.locality or default_locality or None
    street_name = loc.street_name.strip()
    raw_frag = loc.raw_fragment or (f"{street_name} {loc.building_numbers}".strip())

    # Case 1: Whole street explicitly requested or no building numbers given
    if loc.is_whole_street or (not loc.building_numbers and loc.house_low is None):
        return [
            ParsedLocation(
                raw_fragment=raw_frag,
                kind=LocationKind.WHOLE_STREET,
                street=street_name,
                parity=Parity(loc.parity),
                locality=locality,
            )
        ]

    # Case 2: Single range or single house already decomposed by AI
    if loc.house_low is not None and ("," not in loc.building_numbers):
        return [
            ParsedLocation(
                raw_fragment=raw_frag,
                kind=LocationKind.STREET_RANGE,
                street=street_name,
                house_low=loc.house_low,
                house_low_sub=loc.house_low_sub,
                house_high=loc.house_high or loc.house_low,
                house_high_sub=loc.house_high_sub,
                parity=Parity(loc.parity),
                locality=locality,
            )
        ]

    # Case 3: Multiple building numbers or complex ranges in building_numbers string
    tokens = parse_building_clause(loc.building_numbers)
    parsed_locs = []
    for frag, kind_str, low, low_sub, high, high_sub, par in tokens:
        kind = LocationKind.STREET_RANGE if kind_str == "street_range" else LocationKind.WHOLE_STREET
        parsed_locs.append(
            ParsedLocation(
                raw_fragment=f"{street_name} {frag}".strip(),
                kind=kind,
                street=street_name,
                house_low=low,
                house_low_sub=low_sub,
                house_high=high,
                house_high_sub=high_sub,
                parity=Parity(par or loc.parity),
                locality=locality,
            )
        )
    return parsed_locs or [
        ParsedLocation(
            raw_fragment=raw_frag,
            kind=LocationKind.WHOLE_STREET,
            street=street_name,
            locality=locality,
        )
    ]


# ---------------------------------------------------------------------------
# Veolia Post AI Parser
# ---------------------------------------------------------------------------

VEOLIA_SYSTEM_INSTRUCTION = """You are a specialized parser for Armenian water outage announcements from Veolia Jur (Վեոլիա Ջուր).
Your task:
1. Parse the announcement text into structured JSON matching the schema.
2. Standardize dates and times (reference year is provided in the prompt context). Convert Armenian month names into ISO datetimes (YYYY-MM-DDTHH:MM:SS).
3. If the outage spans midnight (e.g. 09:00 - 01:00 or 10:00 - 00:00), adjust the end datetime date to the following day.
4. Extract the administrative hierarchy:
   - For Yerevan: set marz to 'Երևան' and district_or_city to the administrative district (e.g. 'Արաբկիր', 'Կենտրոն', 'Քանաքեռ-Զեյթուն'). If multiple districts are affected, join them with commas (e.g. 'Արաբկիր, Քանաքեռ-Զեյթուն').
   - For Marzes: set marz to the marz name (e.g. 'Արարատ', 'Կոտայք', 'Լոռի') and district_or_city to the city/settlement (e.g. 'Ստեփանավան', 'Լուկաշին').
5. Decompose every affected street, avenue, lane (նրբանցք), or cul-de-sac (փակուղի) and its building numbers/ranges into the locations list.
6. If a street has no specific building numbers, mark is_whole_street=True.
"""

def parse_veolia_post_ai(text: str, *, year: int) -> VeoliaAnnouncement:
    """
    Parse a Veolia Telegram post using Gemini into a VeoliaAnnouncement.
    Raises Exception if API call fails, allowing caller to fall back to regex.
    """
    client = get_genai_client()
    if not client:
        raise RuntimeError("Gemini client unavailable (no API key configured)")

    prompt = f"Reference year is {year}.\nParse this Veolia outage post into structured JSON:\n\n{text}"
    response = _generate_with_fallback(
        client=client,
        contents=prompt,
        system_instruction=VEOLIA_SYSTEM_INSTRUCTION,
        response_schema=VeoliaPostSchema,
    )

    data = VeoliaPostSchema.model_validate_json(response.text)

    # Parse starts_at and ends_at
    starts_at = None
    ends_at = None
    if data.starts_at_iso:
        try:
            starts_at = dt.datetime.fromisoformat(data.starts_at_iso)
        except ValueError:
            pass
    if data.ends_at_iso:
        try:
            ends_at = dt.datetime.fromisoformat(data.ends_at_iso)
        except ValueError:
            pass

    # Ensure rollover if ends_at <= starts_at
    if starts_at and ends_at and ends_at <= starts_at:
        ends_at += dt.timedelta(days=1)

    # Decompose locations
    all_locations: list[ParsedLocation] = []
    for loc_item in data.locations:
        all_locations.extend(ai_location_to_parsed_locations(loc_item, default_locality=data.district_or_city or ""))

    parse_status = "ok" if (starts_at and ends_at and all_locations) else "partial"

    return VeoliaAnnouncement(
        outage_type=data.outage_type,
        marz=data.marz,
        district_or_city=data.district_or_city,
        starts_at=starts_at,
        ends_at=ends_at,
        raw_heading_text=data.raw_heading_text or text.split("\n")[0],
        raw_address_text=data.raw_address_text or text,
        locations=all_locations,
        parse_status=parse_status,
    )


# ---------------------------------------------------------------------------
# ENA Planned Section AI Parser
# ---------------------------------------------------------------------------

ENA_SYSTEM_INSTRUCTION = """You are a specialized parser for Armenian electrical outage announcements from Electric Networks of Armenia (ENA / ՀԷՑ).
Your task:
1. Parse the ENA planned outage text into structured JSON matching the schema.
2. Standardize dates and times (reference year is provided in the prompt context).
3. ENA lists outages per marz or Yerevan district, with specific time slots (e.g. 10:00-13:00, 11:00-16:00).
4. For each time slot under each region:
   - Identify marz_or_yerevan ('Երևան' or Marz name like 'Կոտայք', 'Շիրակ', 'Արարատ').
   - For Yerevan, identify the district ('Կենտրոն', 'Արաբկիր', 'Շենգավիթ', 'Աջափնյակ', etc.).
   - Compute start and end datetimes in ISO format (YYYY-MM-DDTHH:MM:SS).
   - Decompose all affected streets and building numbers/ranges into the locations list.
"""

def parse_ena_day_block_ai(block_text: str, *, is_preliminary: bool, year: int) -> list[EnaPlannedAnnouncement]:
    """
    Parse a single ENA day block using Gemini into a list of EnaPlannedAnnouncement objects.
    """
    client = get_genai_client()
    if not client:
        raise RuntimeError("Gemini client unavailable (no API key configured)")

    prompt = f"Reference year is {year}. Preliminary: {is_preliminary}.\nParse this ENA announcement block into structured JSON:\n\n{block_text}"
    response = _generate_with_fallback(
        client=client,
        contents=prompt,
        system_instruction=ENA_SYSTEM_INSTRUCTION,
        response_schema=EnaDayBlockSchema,
    )

    data = EnaDayBlockSchema.model_validate_json(response.text)

    date_obj = None
    if data.date_iso:
        try:
            date_obj = dt.date.fromisoformat(data.date_iso)
        except ValueError:
            pass

    results: list[EnaPlannedAnnouncement] = []
    for slot in data.slots:
        starts_at = None
        ends_at = None
        if slot.starts_at_iso:
            try:
                starts_at = dt.datetime.fromisoformat(slot.starts_at_iso)
            except ValueError:
                pass
        if slot.ends_at_iso:
            try:
                ends_at = dt.datetime.fromisoformat(slot.ends_at_iso)
            except ValueError:
                pass

        if starts_at and ends_at and ends_at <= starts_at:
            ends_at += dt.timedelta(days=1)

        default_loc = slot.city_or_village or slot.district or ""
        slot_locations: list[ParsedLocation] = []
        for loc_item in slot.locations:
            slot_locations.extend(ai_location_to_parsed_locations(loc_item, default_locality=default_loc))

        parse_status = "ok" if (starts_at and ends_at and slot.raw_address_text) else "partial"

        results.append(
            EnaPlannedAnnouncement(
                outage_type="planned",
                is_preliminary=is_preliminary or data.is_preliminary,
                marz_or_yerevan=slot.marz_or_yerevan,
                district=slot.district,
                date=date_obj or (starts_at.date() if starts_at else None),
                starts_at=starts_at,
                ends_at=ends_at,
                raw_heading_text=slot.raw_heading_text,
                raw_address_text=slot.raw_address_text,
                parse_status=parse_status,
                parsed_locations=slot_locations,
            )
        )

    return results


def parse_ena_section_ai(text: str, *, year: int) -> list[EnaPlannedAnnouncement]:
    """
    Parse an entire ENA planned section using Gemini.
    Splits into day blocks by divider and parses each with AI, falling back
    per block if needed.
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
                results.extend(parse_ena_day_block_ai(sub, is_preliminary=True, year=year))
        else:
            results.extend(parse_ena_day_block_ai(segment, is_preliminary=False, year=year))

    return results
