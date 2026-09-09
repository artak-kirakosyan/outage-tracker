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


def _day_block(month: str, day: int, suffix: str) -> str:
    """Build a minimal but structurally real confirmed day-block: same
    opening-sentence / region-heading / time-window shape as the real
    fixtures, with only the date and a throwaway address varying."""
    return (
        "«Հայաստանի էլեկտրական ցանցեր» ընկերությունը տեղեկացնում է, որ "
        f"{month} {day}-ին պլանային նորոգման աշխատանքներ իրականացնելու "
        "նպատակով ժամանակավորապես կդադարեցվի հետևյալ հասցեների "
        "էլեկտրամատակարարումը՝\n"
        "Կոտայքի մարզ՝\n"
        "10:00-12:00\n"
        f"Թեստային փողոց {suffix},\n"
    )


def test_year_rolls_over_across_a_december_january_boundary():
    """
    Regression: parse_planned_section() previously applied the single
    `year` argument to every day-block on the page uniformly. A page
    fetched near a year boundary can legitimately contain both a
    December day-block and a January one (ENA's own day-blocks already
    span a week-plus ahead in real data — see row_18's Sep 7->14 range)
    — without rollover detection, the January block would silently get
    the wrong (December's) year.
    """
    text = _day_block("դեկտեմբերի", 30, "1") + "\n****************\n" + _day_block("հունվարի", 3, "2")
    results = parse_planned_section(normalize_multiline(text), year=2026)
    dates = sorted({r.date for r in results if r.date})
    assert dates == [datetime.date(2026, 12, 30), datetime.date(2027, 1, 3)]


def test_no_rollover_within_a_single_month_span():
    """Companion to the rollover test: dates that stay within the same
    (or a later, same-year) month must not trigger a bump."""
    text = _day_block("սեպտեմբերի", 4, "1") + "\n****************\n" + _day_block("սեպտեմբերի", 7, "2")
    results = parse_planned_section(normalize_multiline(text), year=2026)
    dates = sorted({r.date for r in results if r.date})
    assert dates == [datetime.date(2026, 9, 4), datetime.date(2026, 9, 7)]


def test_reports_coverage():
    print()
    for label, raw in TEXTS.items():
        text = normalize_multiline(raw)
        results = parse_planned_section(text, year=2026)
        status_counts = {}
        for r in results:
            status_counts[r.parse_status] = status_counts.get(r.parse_status, 0) + 1
        print(f"{label}: {len(results)} announcements -> {status_counts}")
