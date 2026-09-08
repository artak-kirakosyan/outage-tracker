import datetime
import json
from pathlib import Path

from processing.normalize import normalize_multiline
from processing.parsers.ena_planned import parse_planned_section

FIXTURES = Path(__file__).parent / "fixtures"
TEXTS = json.loads((FIXTURES / "ena_planned.json").read_text(encoding="utf-8"))


def test_row2_two_confirmed_dayblocks_no_preliminary():
    text = normalize_multiline(TEXTS["row_2"])
    results = parse_planned_section(text, year=2026)
    dates = sorted({r.date for r in results if r.date})
    assert dates == [datetime.date(2026, 9, 4), datetime.date(2026, 9, 7)]
    assert all(not r.is_preliminary for r in results)


def test_row18_six_dayblocks_two_confirmed_four_preliminary():
    text = normalize_multiline(TEXTS["row_18"])
    results = parse_planned_section(text, year=2026)
    dates = sorted({r.date for r in results if r.date})
    assert dates == [datetime.date(2026, 9, d) for d in (7, 8, 9, 10, 11, 14)]
    confirmed_dates = {r.date for r in results if r.date and not r.is_preliminary}
    preliminary_dates = {r.date for r in results if r.date and r.is_preliminary}
    assert confirmed_dates == {datetime.date(2026, 9, d) for d in (7, 8)}
    assert preliminary_dates == {datetime.date(2026, 9, d) for d in (9, 10, 11, 14)}


def test_no_announcement_fails_to_parse():
    text = normalize_multiline(TEXTS["row_18"])
    results = parse_planned_section(text, year=2026)
    failed = [r for r in results if r.parse_status == "failed"]
    assert not failed, f"{len(failed)} announcement(s) failed entirely: {[r.raw_heading_text for r in failed]}"


def test_region_extraction_on_known_real_example():
    text = normalize_multiline(TEXTS["row_18"])
    results = parse_planned_section(text, year=2026)
    kentron = [r for r in results if r.marz_or_yerevan == "Երևան" and r.district == "Կենտրոն"]
    assert kentron, "expected at least one Kentron (Yerevan) announcement"
    # real example: 10:00-13:00 Sari Tagh block
    sari_tagh = [r for r in kentron if "Սարի Թաղ" in r.raw_address_text]
    assert sari_tagh
    assert sari_tagh[0].starts_at.strftime("%H:%M") == "10:00"
    assert sari_tagh[0].ends_at.strftime("%H:%M") == "13:00"


def test_marz_extraction_on_known_real_example():
    text = normalize_multiline(TEXTS["row_18"])
    results = parse_planned_section(text, year=2026)
    # Exact match, not substring: marz is currently stored in the
    # inflected/genitive form the source text uses ("Արարատի"), not
    # canonical nominative ("Արարատ") — normalization to canonical form
    # is deliberately deferred (see plan doc §7). A substring check here
    # would silently pass either form and mask that fact.
    ararat = [r for r in results if r.marz_or_yerevan == "Արարատի"]
    assert ararat, "expected at least one Ararat marz announcement"
    assert any("Այգեզարդ" in r.raw_address_text for r in ararat)


def test_reports_coverage():
    print()
    for label, raw in TEXTS.items():
        text = normalize_multiline(raw)
        results = parse_planned_section(text, year=2026)
        status_counts = {}
        for r in results:
            status_counts[r.parse_status] = status_counts.get(r.parse_status, 0) + 1
        print(f"{label}: {len(results)} announcements -> {status_counts}")
