"""ENA planned location decomposition — gold cases + corpus smoke."""
from pathlib import Path

import pytest

from processing.address_grammar import LocationKind, Qualifier, parse_address_list
from processing.normalize import normalize_text
from processing.parsers.ena_locations import parse_ena_locations, split_locality_segments

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures"


def _load_addresses():
    import json

    return json.loads((FIXTURES / "ena_addresses.json").read_text(encoding="utf-8"))


def test_simple_house_list():
    locs = parse_ena_locations(
        "Շարուրի փողոց 7, 8, 9 շենքեր և հարակից ոչ բնակիչ-բաժանորդներ"
    )
    assert [loc.street for loc in locs] == ["Շարուրի", "Շարուրի", "Շարուրի"]
    assert all(loc.kind == LocationKind.STREET_RANGE for loc in locs)
    assert locs[0].house_low == 7 and locs[2].house_high == 9


def test_village_list_with_plural_propagation_and_qualifier():
    locs = parse_ena_locations("Ուջան գյուղ մասնակի, Աշնակ, Կաթնաղբյուր, Դավթաշեն գյուղեր")
    assert len(locs) == 4
    assert all(loc.kind == LocationKind.WHOLE_AREA for loc in locs)
    assert [loc.street for loc in locs] == ["Ուջան", "Աշնակ", "Կաթնաղբյուր", "Դավթաշեն"]
    assert locs[0].qualifier == Qualifier.PARTIAL


def test_nested_ordinal_streets_with_qualifiers():
    locs = parse_ena_locations(
        "Վարդենիկ գյուղ՝ 37-րդ, 38-րդ փողոցներն ամբողջությամբ, 11-րդ փողոց մասնակի "
        "և հարակից բոլոր ոչ բնակիչ-բաժանորդներ"
    )
    assert len(locs) == 3
    assert {loc.locality for loc in locs} == {"Վարդենիկ գյուղ"}
    assert [loc.street for loc in locs] == ["37-րդ", "38-րդ", "11-րդ"]
    assert locs[1].qualifier == Qualifier.ENTIRE
    assert locs[2].qualifier == Qualifier.PARTIAL


def test_multi_city_locality_split():
    rows = {r["id"]: r for r in _load_addresses()}
    locs = parse_ena_locations(rows[491]["raw_address_text"])
    localities = {loc.locality for loc in locs if loc.locality}
    assert localities == {"Մասիս քաղաք", "Արարատ քաղաք"}


def test_non_address_only():
    locs = parse_ena_locations(
        "«Գարիկ Հարությունյան», «Արթուր Անաստասյան» ԱՁ-ներ և հարակից ոչ բնակիչ-բաժանորդներ"
    )
    assert locs
    assert all(loc.kind == LocationKind.NON_ADDRESS and not loc.is_matchable for loc in locs)


def test_house_range_and_school_non_address():
    locs = parse_ena_locations(
        "Քաջազնունի փողոց 8/1, 10 շենքերի բնակիչ-բաժանորդներ, "
        "հարակից ոչ բնակիչ-բաժանորդներ, «Նար Դոսի» անվան միջնակարգ դպրոց, "
        "Զավարյան փողոց 72-86 առանձնատներ, Քաջազնունի փողոց 1, 3, 7, 9 շենքեր"
    )
    kinds = [loc.kind for loc in locs]
    assert LocationKind.NON_ADDRESS in kinds
    ranges = [loc for loc in locs if loc.kind == LocationKind.STREET_RANGE]
    assert any(loc.street == "Զավարյան" and loc.house_low == 72 and loc.house_high == 86 for loc in ranges)


def test_compact_ordinal_range_expands():
    locs = parse_address_list(normalize_text("1-7-րդ փողոցներ մասնակի"))
    assert len(locs) == 7
    assert [loc.street for loc in locs] == [f"{n}-րդ" for n in range(1, 8)]
    assert locs[-1].qualifier == Qualifier.PARTIAL


def test_yev_joined_streets():
    locs = parse_address_list(normalize_text("Ռոստովյան և Այվազովսկի փողոցներ մասնակի"))
    assert len(locs) == 2
    assert {loc.street for loc in locs} == {"Ռոստովյան", "Այվազովսկի"}


def test_reject_false_locality_headings():
    # սեփականատեր՝ and փողոց՝ must not split as localities.
    segments = split_locality_segments(
        "Մյասնիկյան պողոտա, սեփականատեր՝ Ռ. Ստեփանյան, Մյասնիկյան փողոց 16-55 առանձնատներ"
    )
    assert len(segments) == 1
    assert segments[0][0] == ""


def test_corpus_smoke_all_sixty_five():
    rows = _load_addresses()
    assert len(rows) == 65
    matchable_announcements = 0
    for row in rows:
        locs = parse_ena_locations(row["raw_address_text"])
        assert isinstance(locs, list)
        for loc in locs:
            if loc.is_matchable:
                assert loc.street
                assert "բնակիչ" not in (loc.street or "")
        if any(loc.is_matchable for loc in locs):
            matchable_announcements += 1
    # Only pure non-address announcements (e.g. id 484) may have zero matchable.
    assert matchable_announcements >= 60
