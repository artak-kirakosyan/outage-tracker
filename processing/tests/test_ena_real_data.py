"""
Tests for ENA planned section parsing against real data extracted from the DB.

These fixtures come from actual fetched raw HTML pages (4 distinct dates),
extracted as BeautifulSoup would return them: HTML tags stripped, HTML entities
decoded to Unicode. That means time separators are en-dashes (U+2013), exactly
as the pipeline receives them. Tests here document two things:

  1. The current pipeline gap: parse_planned_section() without normalize_multiline()
     produces partial records with null times (all 131 DB partial records have this).

  2. The correct behavior once normalize_multiline() is applied: times parse, regions
     are correct, and parse_status is "ok" for all well-structured day-blocks.

See docs/ena-parsing-findings-2026-09-15.md for the full analysis.
"""
import datetime
import json
from pathlib import Path

import pytest

from processing.normalize import normalize_multiline
from processing.parsers.ena_planned import parse_planned_section

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RAW_SECTIONS = json.loads(
    (FIXTURES_DIR / "ena_raw_sections.json").read_text(encoding="utf-8")
)


def _parse(fixture_key: str, year: int = 2026, normalize: bool = True):
    text = RAW_SECTIONS[fixture_key]
    if normalize:
        text = normalize_multiline(text)
    return parse_planned_section(text, year=year)


class TestNormalizationRequired:
    """Document the pipeline gap: en-dash time separators are invisible to the
    parser unless normalize_multiline() is applied first."""

    def test_sep15_without_normalize_all_times_null(self):
        """Without normalization, every record from the Sep 15 all-ndash page
        has null start/end times (parse_status=partial)."""
        results = _parse("rc_531_sep15_confirmed_only", normalize=False)
        assert results
        null_time_records = [r for r in results if r.starts_at is None]
        assert len(null_time_records) == len(results)

    def test_sep15_with_normalize_all_times_present(self):
        """After normalization, ALL records from the Sep 15 all-ndash page
        should have start/end times."""
        results = _parse("rc_531_sep15_confirmed_only", normalize=True)
        null_time_records = [r for r in results if r.starts_at is None]
        assert not null_time_records

    def test_sep11_without_normalize_almost_all_null(self):
        """Sep 11 has 1 hyphen + 78 ndash time ranges. Without normalization,
        only the 1 hyphen-separated time produces an ok record."""
        results = _parse("rc_353_sep11_confirmed_only", normalize=False)
        partial = [r for r in results if r.parse_status == "partial"]
        ok = [r for r in results if r.parse_status == "ok"]
        assert ok
        assert len(partial) > len(ok)

    def test_sep11_with_normalize_no_partial(self):
        """After normalization, no partial records remain for Sep 11."""
        results = _parse("rc_353_sep11_confirmed_only", normalize=True)
        partial = [r for r in results if r.parse_status == "partial"]
        assert not partial


class TestSep15AllNdash:
    """rc_531_sep15_confirmed_only — Sep 15 confirmed-only, pure en-dash separators."""

    @pytest.fixture
    def results(self):
        return _parse("rc_531_sep15_confirmed_only", year=2026)

    def test_single_date_sep15(self, results):
        dates = {r.date for r in results if r.date}
        assert dates == {datetime.date(2026, 9, 15), datetime.date(2026, 9, 16)}

    def test_no_preliminary_records(self, results):
        assert all(not r.is_preliminary for r in results)

    def test_no_failed_or_null_times(self, results):
        assert not [r for r in results if r.parse_status == "failed"]
        assert not [r for r in results if r.starts_at is None or r.ends_at is None]

    def test_known_regions_extracted(self, results):
        marzes = {r.marz_or_yerevan for r in results}
        assert "Երևան" in marzes
        assert "Արմավիրի" in marzes
        assert "Կոտայքի" in marzes
        assert "Շիրակի" in marzes
        assert "Տավուշի" in marzes
        assert "Գեղարքունիքի" in marzes

    def test_kentron_slots(self, results):
        kentron = [r for r in results if r.marz_or_yerevan == "Երևան" and r.district == "Կենտրոն"]
        times = sorted((r.starts_at.strftime("%H:%M"), r.ends_at.strftime("%H:%M")) for r in kentron)
        assert ("11:00", "13:00") in times
        assert ("11:00", "14:00") in times
        assert ("13:00", "16:00") in times


class TestSep4WithPreliminary:
    """rc_18_sep4_with_preliminary — has a preliminary section."""

    @pytest.fixture
    def results(self):
        return _parse("rc_18_sep4_with_preliminary", year=2026)

    def test_has_confirmed_and_preliminary(self, results):
        assert [r for r in results if not r.is_preliminary]
        assert [r for r in results if r.is_preliminary]

    def test_confirmed_dates_are_sep7_and_sep8(self, results):
        confirmed_dates = sorted({r.date for r in results if r.date and not r.is_preliminary})
        assert confirmed_dates == [datetime.date(2026, 9, 7), datetime.date(2026, 9, 8)]

    def test_preliminary_dates_are_future(self, results):
        prelim_dates = sorted({r.date for r in results if r.date and r.is_preliminary})
        confirmed_dates = {r.date for r in results if r.date and not r.is_preliminary}
        assert all(pd > max(confirmed_dates) for pd in prelim_dates)
        assert len(prelim_dates) >= 4

    def test_ararat_marz_sep7(self, results):
        ararat = [r for r in results if r.marz_or_yerevan == "Արարատի" and r.date == datetime.date(2026, 9, 7) and not r.is_preliminary]
        assert ararat
        assert any("Այգեզարդ" in r.raw_address_text for r in ararat)


class TestSep4ConfirmedOnly:
    """rc_2_sep4_confirmed_only — mixed separators."""

    @pytest.fixture
    def results(self):
        return _parse("rc_2_sep4_confirmed_only", year=2026)

    def test_no_null_times(self, results):
        assert not [r for r in results if r.starts_at is None]

    def test_davtashen_slots(self, results):
        davtashen = [r for r in results if r.marz_or_yerevan == "Երևան" and r.district == "Դավթաշեն"]
        times = sorted({(r.starts_at.strftime("%H:%M"), r.ends_at.strftime("%H:%M")) for r in davtashen})
        assert ("11:00", "12:00") in times
        assert ("11:00", "14:00") in times
