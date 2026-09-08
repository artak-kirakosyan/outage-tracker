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
    UNPARSED = "unparsed"          # raw fragment kept, nothing structured


class Parity(str, Enum):
    ANY = "any"
    ODD = "odd"
    EVEN = "even"


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


# Way-type / building-type / area-type words seen in the real Veolia data
# (patterns doc V-1..V-9). Matched as whole words, case-sensitive is fine
# since Veolia's own text is consistently capitalized on these.
_WAY_TYPE_WORDS = ("փողոց", "փող", "պողոտա", "պող", "խճուղի", "խճ", "նրբանցք", "նրբ", "փակուղի", "փակ")
_BUILDING_TYPE_WORDS = ("շենք", "շենքեր", "շենքերի", "շենք1", "առանձնատուն", "առանձնատներ", "տների")
_AREA_TYPE_WORDS = ("գյուղ", "գյուղի", "թաղամաս", "թաղամասի")
# Trailing "streets" noun (not a way-type suffix on a name — this is the
# plural/genitive noun describing what the preceding numbers *are*,
# e.g. "12, 14 փողոցների" = "streets 12, 14"). Overlaps in stem with
# _WAY_TYPE_WORDS, which strips "փող."-style suffixes off names instead
# — the two lists are used in different roles, not merged, since a name
# suffix and a trailing "these numbers are streets" noun are different
# grammatical jobs even though they share a root word.
_STREET_NUMBER_WORDS = ("փողոցների", "փողոցներ", "փողոցի", "փողոց")
_PARITY_WORDS = {"զույգ": Parity.EVEN, "կենտ": Parity.ODD}

_NUMBER_TOKEN_RE = re.compile(r"^(\d+)(?:/(\d+))?([Ա-Ֆաֆ]?)$")
# One number expression: "20", "1-2", "2/1-2/6", "4Ա", "58-58/4", "67-80/2".
_NUMBER_EXPR_RE = re.compile(r"\d+(?:/\d+)?[Ա-Ֆաֆ]?(?:-\d+(?:/\d+)?[Ա-Ֆաֆ]?)?")


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


@dataclasses.dataclass
class _PendingNumericItem:
    raw_fragment: str
    low: int
    low_sub: str | None
    high: int
    high_sub: str | None
    after_part: str


def parse_address_list(raw_text: str) -> list[ParsedLocation]:
    """
    Parse a comma-separated location list (already isolated from the
    surrounding sentence) into ParsedLocation rows. Caller is
    responsible for normalize_text()-ing raw_text first.
    """
    items = [i.strip() for i in raw_text.split(",")]
    items = [i for i in items if i]

    results: list[ParsedLocation] = []
    current_street: str | None = None
    pending_clause: list[_PendingNumericItem] = []

    def flush_clause() -> None:
        """
        Finalize the buffered run of numeric items under the current
        street name. Buffered (rather than emitted item-by-item) because
        the street-vs-house-number trailing word can land on the last
        item of the run rather than every item in it — see module
        docstring.
        """
        if not pending_clause:
            return
        is_street_numbering = any(_has_word(p.after_part, _STREET_NUMBER_WORDS) for p in pending_clause)
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
                    # Parity is a house-numbering concept (odd/even side
                    # of a street) — meaningless for street numbers, so
                    # it's only ever detected for a genuine house range.
                    parity=_detect_parity(p.after_part) if kind == LocationKind.STREET_RANGE else Parity.ANY,
                )
            )
        pending_clause.clear()

    for raw_item in items:
        item = raw_item

        # Renamed-street annotation: a '/' before any digit means
        # "current-name/old-name" — keep only the current name.
        first_digit = re.search(r"\d", item)
        slash_pos = item.find("/")
        if slash_pos != -1 and (first_digit is None or slash_pos < first_digit.start()):
            item = item[:slash_pos].strip()

        match = _NUMBER_EXPR_RE.search(item)

        if match is None:
            # No number anywhere in this item: either a pure parity/
            # qualifier fragment, or a bare street/area name.
            if item and all(
                tok in _PARITY_WORDS or tok in ("համարի",) for tok in item.split()
            ):
                # A trailing qualifier-only fragment with nothing to
                # attach it to (no preceding item this call) — nothing
                # to do; see module docstring on retroactive parity.
                continue

            flush_clause()  # a new name always ends the previous street's numeric run

            name = item
            is_area = _has_word(name, _AREA_TYPE_WORDS)
            clean_name = _strip_words(name, _AREA_TYPE_WORDS if is_area else _WAY_TYPE_WORDS)
            current_street = clean_name or name
            results.append(
                ParsedLocation(
                    raw_fragment=raw_item,
                    kind=LocationKind.WHOLE_AREA if is_area else LocationKind.WHOLE_STREET,
                    street=current_street,
                )
            )
            continue

        name_part = item[: match.start()].strip(" ,")
        after_part = item[match.end() :].strip(" ,")
        parsed = _parse_number_expr(match.group(0))

        if parsed is None:
            flush_clause()
            results.append(ParsedLocation(raw_fragment=raw_item, kind=LocationKind.UNPARSED, is_matchable=False))
            continue

        if name_part:
            flush_clause()  # a new named street always ends the previous one's numeric run
            current_street = _strip_words(name_part, _WAY_TYPE_WORDS) or name_part

        if current_street is None:
            # A bare number with nothing preceding it in this list —
            # can't be matched to a street; keep raw, don't guess.
            results.append(ParsedLocation(raw_fragment=raw_item, kind=LocationKind.UNPARSED, is_matchable=False))
            continue

        low, low_sub, high, high_sub = parsed
        pending_clause.append(_PendingNumericItem(raw_item, low, low_sub, high, high_sub, after_part))

    flush_clause()
    return results
