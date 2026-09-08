import json
from pathlib import Path

import pytest

from processing.address_grammar import LocationKind, Parity
from processing.parsers.veolia_telegram import parse_post

FIXTURES = Path(__file__).parent / "fixtures"
POSTS = json.loads((FIXTURES / "veolia_posts.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("post_id", sorted(POSTS.keys()))
def test_every_real_post_parses_without_crashing(post_id):
    result = parse_post(POSTS[post_id], year=2026)
    # A crash is the only real failure here; "failed"/"partial" status
    # is expected for some posts and asserted on specifically below.
    assert result is not None


def test_all_posts_reach_at_least_partial_status():
    statuses = {pid: parse_post(text, year=2026).parse_status for pid, text in POSTS.items()}
    failed = {pid: s for pid, s in statuses.items() if s == "failed"}
    assert not failed, f"posts that failed to parse at all: {failed}"


def test_time_and_address_extraction_succeeds_for_every_post():
    """
    parse_status='failed' only happens when the body regex (time window
    + address list) doesn't match at all — that's the one thing that
    must never happen across real data, since without it there's
    nothing to notify on.
    """
    for pid, text in POSTS.items():
        result = parse_post(text, year=2026)
        assert result.starts_at is not None, f"{pid}: no start time extracted"
        assert result.ends_at is not None, f"{pid}: no end time extracted"
        assert result.raw_address_text, f"{pid}: no address text extracted"


def test_reports_location_parse_coverage():
    """
    Not a pass/fail assertion — prints a coverage summary so parse
    quality is visible, not just "did it crash". Run with -s to see it.
    """
    kind_counts = {}
    total_locations = 0
    unparsed_examples = []
    for pid, text in POSTS.items():
        result = parse_post(text, year=2026)
        for loc in result.locations:
            total_locations += 1
            kind_counts[loc.kind] = kind_counts.get(loc.kind, 0) + 1
            if loc.kind == LocationKind.UNPARSED:
                unparsed_examples.append((pid, loc.raw_fragment))

    print(f"\ntotal locations parsed across {len(POSTS)} posts: {total_locations}")
    for kind, count in sorted(kind_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {kind}: {count} ({100 * count / total_locations:.1f}%)")
    if unparsed_examples:
        print("unparsed examples:")
        for pid, frag in unparsed_examples[:20]:
            print(f"  {pid}: {frag!r}")


def test_known_real_examples_parse_as_expected():
    """Spot-check specific real examples cited in the patterns doc."""

    # V-8: parity, first form (range + 'զույգ')
    result = parse_address_list_of("Կ.Ուլնեցու 58-58/4 զույգ Շենքերի")
    assert result[0].street == "Կ.Ուլնեցու"
    assert result[0].house_low == 58 and result[0].house_high == 58
    assert result[0].house_high_sub == "4"
    assert result[0].parity == Parity.EVEN

    # V-8: parity, second form (bare number + 'կենտ')
    result = parse_address_list_of("Խորենացի 47, 47/1, 49 կենտ համարի շենքերի")
    assert [l.street for l in result] == ["Խորենացի"] * 3
    # documented simplification: parity co-located with a number applies
    # to that item only, not retroactively to earlier items in the list.
    assert result[-1].parity == Parity.ODD
    assert result[0].parity == Parity.ANY

    # V-10 resolved: old-name annotation dropped, kept as a whole street
    result = parse_address_list_of("Հ. Մալյան/Արաբկիր 45 փող., Ազատության 10")
    assert result[0].kind == LocationKind.WHOLE_STREET
    assert result[0].street == "Հ. Մալյան"
    assert result[1].street == "Ազատության"
    assert result[1].house_low == 10

    # V-6: sub-numbered range endpoint, one side only
    result = parse_address_list_of("Ավետ Ավետիսյանի 67-80/2 շենքերի")
    assert result[0].house_low == 67 and result[0].house_low_sub is None
    assert result[0].house_high == 80 and result[0].house_high_sub == "2"

    # V-1/V-2: whole area
    result = parse_address_list_of("Կոռնիձոր գյուղի, ք.Կապան Ձորքի Թաղամասի")
    assert result[0].kind == LocationKind.WHOLE_AREA
    assert result[0].street == "Կոռնիձոր"


def parse_address_list_of(text: str):
    from processing.address_grammar import parse_address_list
    from processing.normalize import normalize_text

    return parse_address_list(normalize_text(text))
