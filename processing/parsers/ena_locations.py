"""
Decompose ENA planned `raw_address_text` into ParsedLocation rows.

Pipeline:
  1. normalize_text
  2. strip P-5 boilerplate trailers
  3. split on real nested locality headings (քաղաք/գյուղ/…)
  4. run address_grammar.parse_address_list per segment
  5. stamp locality onto each location

See docs/ena-low-to-high-confidence.md and docs/data-patterns.md §1.2.
"""
from __future__ import annotations

import re

from processing.address_grammar import (
    ParsedLocation,
    Qualifier,
    _AREA_TYPE_WORDS,
    _WAY_TYPE_WORDS,
    _has_word,
    parse_address_list,
)
from processing.normalize import normalize_text

# Trailing boilerplate on almost every ENA planned list (P-5).
_BOILERPLATE_RE = re.compile(
    r"(?:,\s*)?(?:և\s+)?"
    r"(?:"
    r"հարակից\s+(?:բոլոր\s+)?ոչ\s+բնակիչ-բաժանորդներ|"
    r"հարակից\s+ոչ\s+բնակիչ-բաժանորդներ|"
    r"հարակից\s+տարածք(?:ներ(?:ի)?)?(?:\s+առանձնատներ)?|"
    r"հարակից\s+տարածքների\s+առանձնատներ|"
    r"բոլոր\s+(?:բնակիչ-բաժանորդներ(?:\s+և\s+ոչ\s+բնակիչ-բաժանորդներ)?|"
    r"ոչ\s+բնակիչ-բաժանորդներ)|"
    r"ոչ\s+բնակիչ-բաժանորդներ|"
    r"բնակիչ-բաժանորդներ|"
    r"և\s+կից\s+խանութներ|"
    r"ՊՈԱԿ\s+կազմակերպություններ"
    r")\.?\s*$",
    re.IGNORECASE,
)

# Locality heading: "Մասիս քաղաք՝" or backtick variant. Armenian՝ (U+055D) or `.
_LOCALITY_HEADING_RE = re.compile(
    r"([^,;]+?)[՝`]\s*",
)

# Area vocabulary that makes X՝ a real locality (not սեփականատեր՝ / փողոց՝).
_LOCALITY_AREA_WORDS = _AREA_TYPE_WORDS + (
    "քաղաք", "քաղաքի",
    "համայնք", "համայնքի",
    "տարածաշրջան", "տարածաշրջանի",
)

# Reject headings that are clearly streets / owners.
_LOCALITY_REJECT_WORDS = _WAY_TYPE_WORDS + (
    "փողոցներ", "փողոցների", "փողոցներն", "փողոցն",
    "սեփականատեր", "շենքեր", "շենքերի", "առանձնատներ",
)


def strip_ena_boilerplate(text: str) -> str:
    """Remove P-5 subscriber boilerplate; keep the address list itself."""
    # Only strip trailers at the very end (not mid-list "և հարակից…, next street").
    prev = None
    while prev != text:
        prev = text
        text = _BOILERPLATE_RE.sub("", text).strip(" ,;.")
    # Drop comma-items that are boilerplate-only.
    parts = [p.strip() for p in text.split(",")]
    kept = []
    for p in parts:
        if not p:
            continue
        if re.fullmatch(
            r"(?:և\s+)?(?:հարակից\s+)?(?:բոլոր\s+)?(?:ոչ\s+)?բնակիչ-բաժանորդներ(?:ի)?",
            p,
        ):
            continue
        if re.fullmatch(r"(?:և\s+)?հարակից\s+տարածք(?:ներ(?:ի)?)?(?:\s+առանձնատներ)?", p):
            continue
        kept.append(p)
    return ", ".join(kept).strip(" ,;.")


def _is_locality_heading(heading: str) -> bool:
    heading = heading.strip()
    if not heading:
        return False
    if _has_word(heading, _LOCALITY_REJECT_WORDS):
        return False
    if _has_word(heading, _LOCALITY_AREA_WORDS):
        return True
    # Bare place names with no street/number noise (e.g. Ավան-Առինջ).
    if re.search(r"\d", heading):
        # Allow "Նոր Նորք 2-րդ զանգված"
        return _has_word(heading, ("զանգված", "զանգվածի", "թաղամաս", "թաղամասի"))
    # Reject very short or obvious non-places.
    if len(heading) < 3:
        return False
    return not _has_word(heading, ("սեփականատեր",))


def split_locality_segments(text: str) -> list[tuple[str, str]]:
    """
    Split address text into (locality, segment_body) pairs.

    Locality is "" when the list is flat (no nested heading). Multiple
    real localities (Մասիս քաղաք՝ … Արարատ քաղաք՝ …) yield multiple pairs.
    """
    matches = list(_LOCALITY_HEADING_RE.finditer(text))
    real: list[re.Match[str]] = []
    for m in matches:
        # Heading must be at start or right after a comma/semicolon boundary
        # (not mid-street). Check char before match.
        start = m.start()
        if start > 0 and text[start - 1] not in " ,;.\n":
            # Might still be valid if previous char is end of prior segment;
            # require the heading itself to look like a locality.
            pass
        if _is_locality_heading(m.group(1)):
            real.append(m)

    if not real:
        return [("", text.strip())]

    segments: list[tuple[str, str]] = []
    # Text before the first locality heading (rare) keeps empty locality.
    if real[0].start() > 0:
        prefix = text[: real[0].start()].strip(" ,;")
        if prefix:
            segments.append(("", prefix))

    for i, m in enumerate(real):
        locality = m.group(1).strip()
        end = real[i + 1].start() if i + 1 < len(real) else len(text)
        body = text[m.end() : end].strip(" ,;")
        if body:
            segments.append((locality, body))
        else:
            # Heading with empty body — still record as whole_area via grammar
            # by feeding the locality name itself.
            segments.append((locality, locality))
    return segments or [("", text.strip())]


def parse_ena_locations(raw_address_text: str) -> list[ParsedLocation]:
    """
    Full ENA planned address-list → ParsedLocation decomposition.
    """
    if not (raw_address_text or "").strip():
        return []

    text = normalize_text(raw_address_text)
    text = strip_ena_boilerplate(text)
    if not text:
        return []

    results: list[ParsedLocation] = []
    for locality, body in split_locality_segments(text):
        body = strip_ena_boilerplate(body)
        if not body:
            continue
        # If body is only the locality name repeated, emit one whole_area.
        locs = parse_address_list(body)
        for loc in locs:
            results.append(
                ParsedLocation(
                    raw_fragment=loc.raw_fragment,
                    kind=loc.kind,
                    street=loc.street,
                    house_low=loc.house_low,
                    house_low_sub=loc.house_low_sub,
                    house_high=loc.house_high,
                    house_high_sub=loc.house_high_sub,
                    parity=loc.parity,
                    is_matchable=loc.is_matchable,
                    locality=locality or loc.locality,
                    qualifier=loc.qualifier if loc.qualifier != Qualifier.NONE else loc.qualifier,
                )
            )
    return results
