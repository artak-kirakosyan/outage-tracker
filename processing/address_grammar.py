"""
Parser for the comma-separated "location list" grammar documented in
outage-data-patterns-v2.md sections 2.3 (Veolia V-1..V-9).

Grammar summary (see the patterns doc for full real examples):
    item := [ name ] [ number-expr ] [ trailing-words ]
A comma-separated list of items, where a name-less item continues the
most recently named street ("current street" state machine, V-7), a
name with no number is a whole street/area on its own, and trailing
words after a number-expr may carry a building-type descriptor (ignored
for matching) or a parity word (kept).

Street numbers vs. house numbers (fixed, see the processing plan doc):
  Some outlying districts (Նոր Արեշ, Վարդաշեն, Մուշական, ...) number
  their *streets* rather than naming them, so "Նոր Արեշ 12, 14
  փողոցների" means streets 12 and 14 of the Nor Aresh area, not house
  numbers 12/14 on a street literally named "Նոր Արեշ". Rather than
  hardcode a list of which districts do this (incomplete and brittle —
  ENA/Veolia could add more at any time), the source text already
  marks it grammatically: a number-group whose trailing word is a
  "streets" noun (`փողոց`/`փողոցի`/`փողոցներ`/`փողոցների`) rather than
  a building noun (`շենք(եր)(ի)`, `առանձնատներ`) is a street-number
  range, not a house range. Since that trailing word can land on the
  *last* item of a multi-item run sharing one street name (e.g. "Նոր
  Արեշ 12, 14 փողոցների" — "12" and "14 փողոցների" are two comma
  items), detection needs the whole run of numeric items under one
  street name, not just one item in isolation — see `_flush_clause`.
  Residual limitation: if a numbered-street list is ever phrased
  without that trailing word, this still misclassifies as a house
  range. No real example of that gap has been seen so far.

Ordinal numbered-quarter names (fixed, see the processing plan doc):
  ENA's data confirms a "N-րդ <noun>" ordinal shape for numbered
  quarters/blocks, e.g. "Նոր Նորք 8-րդ զանգված" ("Nor Nork, 8th
  block"). Without special handling, `_NUMBER_EXPR_RE` would match the
  bare "8" as if it were a house number, silently dropping "զանգված"
  (and anything chained after it) into the discarded parity-detection
  text — misparsing, not just failing to parse. Detected via a literal
  "-րդ" immediately after the matched digits and routed through the
  name-handling branch instead, so the ordinal stays attached to the
  area name it actually describes. Not yet observed in real Veolia
  data (only in ENA's, which isn't decomposed through this grammar at
  all — see ena_planned.py), but the same numbered Yerevan districts
  appear in both sources, so it's handled defensively here.

Known, documented simplifications (see the processing plan doc):
  - Parity words found together with a number apply to that item only.
    A parity word trailing a whole comma-list (no number of its own)
    is NOT retroactively applied to earlier items in v1 — this differs
    from how a human reader would probably interpret e.g. "47, 47/1, 49
    կենտ համարի շենքերի", but resolving that requires clause-level
    lookahead that isn't worth the complexity for the one real example
    seen so far. Flagged for revisit if it turns out to matter.
  - Sub-numbered range endpoints (`67-80/2`) are stored exactly as
    parsed (`sub=None` when absent) rather than synthesizing an
    implicit "/1" on the bare end. The implicit-/1 interpretation is a
    documented *matching-time* rule (see the plan doc), not applied
    here — parsing should stay faithful to what the source actually
    said.
  - `X/Y N <way-type>` where the slash appears before any digit (e.g.
    "Հ. Մալյան/Արաբկիր 45 փող.") is treated as a renamed-street
    decorative annotation: everything from the slash onward is
    dropped, keeping only the name before it. Confirmed real case:
    "Արաբկիր 45" is the old, pre-rename name of "Հ. Մալյան" street.
    This never collides with sub-numbered ranges (`80/2`), where the
    slash always appears *after* a digit.
"""
import dataclasses
import re
from enum import Enum


class LocationKind(str, Enum):
    WHOLE_AREA = "whole_area"      # settlement, quarter, or district — no street
    WHOLE_STREET = "whole_street"  # a named street with no number given
    STREET_RANGE = "street_range"  # a street + a house number or house-number range
    STREET_NUMBER_RANGE = "street_number_range"  # a numbered-street area + a street-number or range (not house numbers)
    NON_ADDRESS = "non_address"    # business / institution / owner — never matchable
    UNPARSED = "unparsed"          # raw fragment kept, nothing structured


class Parity(str, Enum):
    ANY = "any"
    ODD = "odd"
    EVEN = "even"


class Qualifier(str, Enum):
    """ENA մասնակի / ամբողջությամբ — stored for copy, not used to downgrade match confidence."""

    NONE = ""
    PARTIAL = "partial"
    ENTIRE = "entire"


@dataclasses.dataclass
class ParsedLocation:
    raw_fragment: str
    kind: LocationKind
    street: str | None = None
    house_low: int | None = None
    house_low_sub: str | None = None
    house_high: int | None = None
    house_high_sub: str | None = None
    parity: Parity = Parity.ANY
    is_matchable: bool = True
    locality: str | None = None
    qualifier: Qualifier = Qualifier.NONE


# Way-type / building-type / area-type words seen in the real Veolia + ENA data
# (patterns doc V-1..V-9, P-1..P-5). Matched as whole words.
_WAY_TYPE_WORDS = (
    "փողոց", "փող", "պողոտա", "պող", "խճուղի", "խճ", "նրբանցք", "նրբ",
    "փակուղի", "փակ", "անցուղի", "անցուղին", "մայրուղի", "մայրուղին",
)
_BUILDING_TYPE_WORDS = (
    "շենք", "շենքեր", "շենքերի", "շենք1", "առանձնատուն", "առանձնատներ",
    "տների", "հասցե", "հասցեներ",
)
_AREA_TYPE_WORDS = (
    "գյուղ", "գյուղի", "գյուղեր", "գյուղերն", "գյուղն",
    "թաղամաս", "թաղամասի", "թաղամասեր",
    "զանգված", "զանգվածի",
    "քաղաք", "քաղաքի",
    "համայնք", "համայնքի",
    "տարածաշրջան", "տարածաշրջանի",
)
# Trailing "streets" noun (not a way-type suffix on a name — this is the
# plural/genitive noun describing what the preceding numbers *are*,
# e.g. "12, 14 փողոցների" = "streets 12, 14"). Overlaps in stem with
# _WAY_TYPE_WORDS, which strips "փող."-style suffixes off names instead
# — the two lists are used in different roles, not merged, since a name
# suffix and a trailing "these numbers are streets" noun are different
# grammatical jobs even though they share a root word.
_STREET_NUMBER_WORDS = (
    "փողոցների", "փողոցներ", "փողոցներն", "փողոցի", "փողոց", "փողոցն",
)
_PARITY_WORDS = {"զույգ": Parity.EVEN, "կենտ": Parity.ODD}
_QUALIFIER_WORDS = {
    "մասնակի": Qualifier.PARTIAL,
    "ամբողջությամբ": Qualifier.ENTIRE,
}
# Plural settlement nouns that propagate backward over a bare-name run
# (ENA: "Աշնակ, Կաթնաղբյուր, Դավթաշեն գյուղեր").
_PLURAL_AREA_WORDS = ("գյուղեր", "գյուղերն", "թաղամասեր")

_NUMBER_TOKEN_RE = re.compile(r"^(\d+)(?:/(\d+))?([Ա-Ֆա-ֆ]?)$")
# One number expression: "20", "1-2", "2/1-2/6", "4Ա", "58-58/4", "67-80/2".
_NUMBER_EXPR_RE = re.compile(r"\d+(?:/\d+)?[Ա-Ֆա-ֆ]?(?:-\d+(?:/\d+)?[Ա-Ֆա-ֆ]?)?")


def _parse_number_token(token: str) -> tuple[int, str | None] | None:
    m = _NUMBER_TOKEN_RE.match(token)
    if not m:
        return None
    main = int(m.group(1))
    sub = m.group(2) or (m.group(3) or None)
    return main, sub


def _parse_number_expr(expr: str) -> tuple[int, str | None, int, str | None] | None:
    parts = expr.split("-", 1)
    low = _parse_number_token(parts[0])
    if low is None:
        return None
    if len(parts) == 1:
        return low[0], low[1], low[0], low[1]
    high = _parse_number_token(parts[1])
    if high is None:
        return None
    return low[0], low[1], high[0], high[1]


def _has_word(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![Ա-֏]){re.escape(w)}(?![Ա-֏])", text) for w in words)


def _strip_words(text: str, words: tuple[str, ...]) -> str:
    for w in words:
        text = re.sub(rf"(?<![Ա-֏]){re.escape(w)}\.?(?![Ա-֏])", " ", text)
    return re.sub(r"\s+", " ", text).strip(" .,")


def _detect_parity(text: str) -> Parity:
    for word, parity in _PARITY_WORDS.items():
        if word in text:
            return parity
    return Parity.ANY


def _detect_qualifier(text: str) -> Qualifier:
    for word, qualifier in _QUALIFIER_WORDS.items():
        if _has_word(text, (word,)):
            return qualifier
    return Qualifier.NONE


def _strip_qualifiers(text: str) -> str:
    return _strip_words(text, tuple(_QUALIFIER_WORDS.keys()))


# Civic / business markers — fragment is not a residential match target.
_NON_ADDRESS_MARKERS = (
    "ՍՊԸ", "ՓԲԸ", "ԱՁ", "ՊՈԱԿ", "ՀՈԱԿ",
    "դպրոց", "մանկապարտեզ", "մսուր", "ծննդատուն",
    "զորամաս", "զինմաս", "գազալցակայան", "գազալցակայաններ",
    "Կադաստր", "Քաղաքապետարան", "Շուկա",
    "ինստիտուտ", "առողջարան", "հանգստյան", "հանգստի",
    "օպերատոր", "օպերատորի", "օպերատորների", "կայաններ",
    "սեփականատեր", "ընկերության", "ընկերությունների",
)
_NON_ADDRESS_RE = re.compile(r"թիվ\s*\d+")
_COMPACT_ORDINAL_RANGE_RE = re.compile(r"\b(\d+)-(\d+)-(րդ|ին)\b")
_ORDINAL_TOKEN_RE = re.compile(r"^(\d+)-(րդ|ին)$")
_YEV_SPLIT_RE = re.compile(r"\s+և\s+")


def _is_non_address(text: str) -> bool:
    if "«" in text or "»" in text:
        return True
    if _NON_ADDRESS_RE.search(text):
        return True
    return _has_word(text, _NON_ADDRESS_MARKERS)


def _expand_yev_joins(items: list[str]) -> list[str]:
    """Split 'A և B փողոցներ' into two comma-items sharing trailing nouns."""
    expanded: list[str] = []
    for item in items:
        parts = _YEV_SPLIT_RE.split(item)
        if len(parts) != 2:
            expanded.append(item)
            continue
        left, right = parts[0].strip(), parts[1].strip()
        if not left or not right:
            expanded.append(item)
            continue
        # Don't split numeric house lists joined by և (rare); only name-like.
        if _NUMBER_EXPR_RE.fullmatch(left.replace(" ", "")):
            expanded.append(item)
            continue
        # Don't split '... շենքեր և հարակից ոչ բնակիչ-բաժանորդներ'.
        if "բնակիչ-բաժանորդ" in right or right.startswith("հարակից") or right.startswith("կից"):
            # Keep left only; drop boilerplate right-hand side.
            expanded.append(left)
            continue
        expanded.append(left)
        expanded.append(right)
    return expanded


def _expand_compact_ordinal_ranges(items: list[str]) -> list[str]:
    """Expand '1-7-րդ փողոցներ' into '1-րդ', '2-րդ', ... '7-րդ փողոցներ'."""
    expanded: list[str] = []
    for item in items:
        m = _COMPACT_ORDINAL_RANGE_RE.search(item)
        if not m:
            expanded.append(item)
            continue
        low, high, suffix = int(m.group(1)), int(m.group(2)), m.group(3)
        if high < low or high - low > 40:
            expanded.append(item)
            continue
        prefix = item[: m.start()].strip()
        trailing = item[m.end() :].strip()
        for n in range(low, high + 1):
            piece = f"{n}-{suffix}"
            if n == low and prefix:
                piece = f"{prefix} {piece}"
            if n == high and trailing:
                piece = f"{piece} {trailing}"
            expanded.append(piece.strip())
    return expanded


@dataclasses.dataclass
class _PendingNumericItem:
    raw_fragment: str
    low: int
    low_sub: str | None
    high: int
    high_sub: str | None
    after_part: str
    qualifier: Qualifier = Qualifier.NONE


def _apply_plural_area_propagation(results: list[ParsedLocation]) -> None:
    """
    ENA: 'Աշնակ, Կաթնաղբյուր, Դավթաշեն գյուղեր' — the plural area noun on
    the last item applies backward to preceding bare names. Ambiguous
    'գյուղ1, գյուղ2 մասնակի' keeps qualifier on the last item only.
    """
    i = 0
    while i < len(results):
        loc = results[i]
        if loc.kind not in (LocationKind.WHOLE_AREA, LocationKind.WHOLE_STREET):
            i += 1
            continue
        if not loc.street or not _has_word(loc.raw_fragment, _PLURAL_AREA_WORDS):
            i += 1
            continue
        # Walk backward over consecutive bare whole_street names.
        j = i - 1
        while j >= 0:
            prev = results[j]
            if prev.kind != LocationKind.WHOLE_STREET or not prev.is_matchable:
                break
            if prev.qualifier != Qualifier.NONE:
                break
            # Don't rewrite something that already looks like a street.
            if _has_word(prev.raw_fragment, _WAY_TYPE_WORDS + _STREET_NUMBER_WORDS):
                break
            results[j] = ParsedLocation(
                raw_fragment=prev.raw_fragment,
                kind=LocationKind.WHOLE_AREA,
                street=prev.street,
                is_matchable=True,
                locality=prev.locality,
                qualifier=prev.qualifier,
            )
            j -= 1
        # Clean plural noun off the last item's street name.
        clean = _strip_words(loc.street, _AREA_TYPE_WORDS)
        results[i] = ParsedLocation(
            raw_fragment=loc.raw_fragment,
            kind=LocationKind.WHOLE_AREA,
            street=clean or loc.street,
            is_matchable=loc.is_matchable,
            locality=loc.locality,
            qualifier=loc.qualifier,
        )
        i += 1


def parse_address_list(raw_text: str) -> list[ParsedLocation]:
    """
    Parse a comma-separated location list (already isolated from the
    surrounding sentence) into ParsedLocation rows. Caller is
    responsible for normalize_text()-ing raw_text first.

    Handles both Veolia's flat lists and ENA planned-list extras
    (qualifiers, plural village runs, և-joins, ordinal streets,
    non-address entities). Locality scoping is applied by the ENA
    caller after this returns — see processing/parsers/ena_locations.py.
    """
    items = [i.strip() for i in raw_text.split(",")]
    items = [i for i in items if i]
    items = _expand_yev_joins(items)
    items = _expand_compact_ordinal_ranges(items)

    results: list[ParsedLocation] = []
    current_street: str | None = None
    pending_clause: list[_PendingNumericItem] = []

    def flush_clause() -> None:
        if not pending_clause:
            return
        is_street_numbering = any(
            _has_word(p.after_part, _STREET_NUMBER_WORDS) for p in pending_clause
        )
        # Ordinal street lists: "8-րդ, 3-րդ, … փողոցներ" were routed here
        # only when the number path ran — ordinals take the name path.
        # Bare numbers + trailing փողոցներ → STREET_NUMBER_RANGE (Veolia).
        kind = LocationKind.STREET_NUMBER_RANGE if is_street_numbering else LocationKind.STREET_RANGE
        for p in pending_clause:
            results.append(
                ParsedLocation(
                    raw_fragment=p.raw_fragment,
                    kind=kind,
                    street=current_street,
                    house_low=p.low,
                    house_low_sub=p.low_sub,
                    house_high=p.high,
                    house_high_sub=p.high_sub,
                    parity=_detect_parity(p.after_part) if kind == LocationKind.STREET_RANGE else Parity.ANY,
                    qualifier=p.qualifier or _detect_qualifier(p.after_part),
                )
            )
        pending_clause.clear()

    for raw_item in items:
        item = raw_item.strip(" ,;")
        if not item:
            continue

        item_qualifier = _detect_qualifier(item)
        item = _strip_qualifiers(item).strip(" ,;")

        if _is_non_address(item):
            flush_clause()
            results.append(
                ParsedLocation(
                    raw_fragment=raw_item,
                    kind=LocationKind.NON_ADDRESS,
                    street=None,
                    is_matchable=False,
                    qualifier=item_qualifier,
                )
            )
            current_street = None
            continue

        # Renamed-street annotation: a '/' before any digit means
        # "current-name/old-name" — keep only the current name.
        first_digit = re.search(r"\d", item)
        slash_pos = item.find("/")
        if slash_pos != -1 and (first_digit is None or slash_pos < first_digit.start()):
            item = item[:slash_pos].strip()

        match = _NUMBER_EXPR_RE.search(item)

        # Ordinal marker ("8-րդ" / "1-ին") — not a house number. Keep as
        # a street/area name (ENA numbered streets, Nor Nork blocks).
        is_ordinal = False
        if match is not None:
            rest = item[match.end() :]
            if rest.startswith("-րդ") or rest.startswith("-ին"):
                is_ordinal = True
                match = None

        if match is None:
            # Pure parity/qualifier fragment with nothing to attach to.
            tokens = item.split()
            if item and all(tok in _PARITY_WORDS or tok in ("համարի",) for tok in tokens):
                continue
            if not item:
                continue

            flush_clause()

            name = item
            # "Նոր Նորք 8-րդ զանգված" is an area (ordinal quarter), not a street.
            is_area = _has_word(name, _AREA_TYPE_WORDS)
            if is_ordinal and not is_area:
                # Ordinal street: "37-րդ փողոց" / bare "37-րդ" → whole_street.
                clean_name = _strip_words(name, _WAY_TYPE_WORDS + _STREET_NUMBER_WORDS)
                street_name = clean_name or name
                current_street = street_name
                results.append(
                    ParsedLocation(
                        raw_fragment=raw_item,
                        kind=LocationKind.WHOLE_STREET,
                        street=current_street,
                        qualifier=item_qualifier,
                    )
                )
                continue

            strip_set = _AREA_TYPE_WORDS if is_area else (_WAY_TYPE_WORDS + _STREET_NUMBER_WORDS)
            clean_name = _strip_words(name, strip_set)
            current_street = clean_name or name
            results.append(
                ParsedLocation(
                    raw_fragment=raw_item,
                    kind=LocationKind.WHOLE_AREA if is_area else LocationKind.WHOLE_STREET,
                    street=current_street,
                    qualifier=item_qualifier,
                )
            )
            continue

        name_part = item[: match.start()].strip(" ,")
        after_part = item[match.end() :].strip(" ,")
        parsed = _parse_number_expr(match.group(0))

        if parsed is None:
            flush_clause()
            results.append(
                ParsedLocation(raw_fragment=raw_item, kind=LocationKind.UNPARSED, is_matchable=False)
            )
            continue

        if name_part:
            flush_clause()
            current_street = _strip_words(name_part, _WAY_TYPE_WORDS) or name_part

        if current_street is None:
            results.append(
                ParsedLocation(raw_fragment=raw_item, kind=LocationKind.UNPARSED, is_matchable=False)
            )
            continue

        low, low_sub, high, high_sub = parsed
        pending_clause.append(
            _PendingNumericItem(
                raw_item, low, low_sub, high, high_sub, after_part, item_qualifier
            )
        )

    flush_clause()
    _apply_plural_area_propagation(results)
    return results
