from pathlib import Path
from unittest import mock

import pytest
from django.core.management import call_command

from ingestion.models import FetchStatus, Provider, RawContent, SourceType
from processing.models import OutageAnnouncement, OutageLocation

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures"


def _make_raw_content(*, provider, source_type, content, reference="https://example.test/"):
    return RawContent.objects.create(
        provider=provider,
        source_type=source_type,
        reference=reference,
        content=content,
        fetch_status=FetchStatus.OK,
    )


def _ena_html(section_body: str) -> str:
    return f'<html><body><div id="ctl00_MainContent_attenbody">{section_body}</div></body></html>'


def _ena_confirmed_day_block(month: str, day: int) -> str:
    """Minimal but structurally real ENA day-block: same opening-sentence
    / region-heading / time-window shape parse_planned_section() needs
    (mirrors processing/tests/test_ena_planned.py's own _day_block
    helper). Deliberately plain-ASCII punctuation so it doesn't also
    exercise normalize_multiline() concerns -- unrelated to what these
    tests are checking."""
    return (
        "«Հայաստանի էլեկտրական ցանցեր» ընկերությունը տեղեկացնում է, որ "
        f"{month} {day}-ին պլանային նորոգման աշխատանքներ իրականացնելու "
        "նպատակով ժամանակավորապես կդադարեցվի հետևյալ հասցեների "
        "էլեկտրամատակարարումը` "
        "Կոտայքի մարզ` "
        "10:00-12:00 "
        "Թեստային փողոց 1, "
    )


def test_processes_veolia_page_into_announcements_and_locations():
    html = (FIXTURES / "veolia_telegram_page_sample.html").read_text(encoding="utf-8")
    _make_raw_content(provider=Provider.VEOLIA_TELEGRAM, source_type=SourceType.TELEGRAM_TEXT, content=html)

    call_command("process_raw_content")

    assert OutageAnnouncement.objects.filter(provider=Provider.VEOLIA_TELEGRAM).count() == 3
    assert OutageLocation.objects.count() > 0
    assert RawContent.objects.get().processed is True

    announcement = OutageAnnouncement.objects.get(external_ref="VeoliaJur/14500")
    assert announcement.marz == "Արմավիրի"
    assert announcement.starts_at is not None
    assert announcement.starts_at.tzinfo is not None  # localized, not naive


def test_processes_ena_page_into_announcements_with_locations():
    html = (FIXTURES / "ena_page_sample.html").read_text(encoding="utf-8")
    _make_raw_content(provider=Provider.ENA, source_type=SourceType.HTML, content=html)

    call_command("process_raw_content")

    announcements = OutageAnnouncement.objects.filter(provider=Provider.ENA)
    assert announcements.count() > 0
    assert OutageLocation.objects.filter(announcement__provider=Provider.ENA).count() > 0
    assert RawContent.objects.get().processed is True


def test_rerunning_is_idempotent_no_duplicate_announcements():
    html = (FIXTURES / "veolia_telegram_page_sample.html").read_text(encoding="utf-8")
    raw = _make_raw_content(provider=Provider.VEOLIA_TELEGRAM, source_type=SourceType.TELEGRAM_TEXT, content=html)

    call_command("process_raw_content")
    first_count = OutageAnnouncement.objects.count()
    first_last_seen = OutageAnnouncement.objects.get(external_ref="VeoliaJur/14500").last_seen_at

    # A second RawContent row with the same page content -- simulates
    # the Telegram preview showing the same last-N posts on a re-poll.
    raw.processed = False
    raw.save(update_fields=["processed"])
    call_command("process_raw_content")

    assert OutageAnnouncement.objects.count() == first_count
    second_last_seen = OutageAnnouncement.objects.get(external_ref="VeoliaJur/14500").last_seen_at
    assert second_last_seen >= first_last_seen


def test_error_status_rows_are_never_processed():
    RawContent.objects.create(
        provider=Provider.ENA,
        source_type=SourceType.HTML,
        reference="https://example.test/",
        content="",
        fetch_status=FetchStatus.ERROR,
        error_message="boom",
    )

    call_command("process_raw_content")

    assert OutageAnnouncement.objects.count() == 0
    # Untouched -- error rows are outside this command's queryset entirely.
    assert RawContent.objects.get().processed is False


def test_extraction_failure_marks_processed_without_crashing():
    """An OK-status row whose markup doesn't match expectations must be
    marked processed (so it isn't retried forever) rather than raising."""
    from processing.dashboard import EXTRACTION_FAILED_PREFIX

    _make_raw_content(
        provider=Provider.ENA, source_type=SourceType.HTML, content="<html><body>unexpected markup</body></html>"
    )

    call_command("process_raw_content")  # must not raise

    raw = RawContent.objects.get()
    assert OutageAnnouncement.objects.count() == 0
    assert raw.processed is True
    assert raw.error_message.startswith(EXTRACTION_FAILED_PREFIX)


def test_ena_announcement_is_preliminary_is_downgraded_on_reconfirmation():
    """
    Regression: ena_external_ref() deliberately excludes is_preliminary
    (see its docstring) so an unchanged day-block re-seen later as
    confirmed matches the same row instead of creating a duplicate --
    but that only helps if the existing row's is_preliminary actually
    gets updated when that happens. Before the fix in _process_ena, the
    row stayed stuck showing is_preliminary=True forever once ENA
    confirmed it.
    """
    preliminary_html = _ena_html(
        "Պլանային անջատումների մասին նախնական տեղեկատվություն "
        + _ena_confirmed_day_block("սեպտեմբերի", 20)
    )
    _make_raw_content(provider=Provider.ENA, source_type=SourceType.HTML, content=preliminary_html)
    call_command("process_raw_content")

    assert OutageAnnouncement.objects.filter(provider=Provider.ENA).count() == 1
    announcement = OutageAnnouncement.objects.get(provider=Provider.ENA)
    assert announcement.is_preliminary is True
    external_ref = announcement.external_ref

    # A later fetch shows the same, unchanged day-block now confirmed
    # (no "preliminary information" wrapper) -- same date/region/time/
    # address, so it hashes to the same external_ref.
    confirmed_html = _ena_html(_ena_confirmed_day_block("սեպտեմբերի", 20))
    _make_raw_content(provider=Provider.ENA, source_type=SourceType.HTML, content=confirmed_html)
    call_command("process_raw_content")

    assert OutageAnnouncement.objects.filter(provider=Provider.ENA).count() == 1, (
        "the confirmed sighting should update the existing row, not create a second one"
    )
    announcement.refresh_from_db()
    assert announcement.external_ref == external_ref
    assert announcement.is_preliminary is False

    # A further sighting still listed as preliminary (unexpected, but
    # shouldn't happen for real data) must not flip a confirmed row back.
    _make_raw_content(provider=Provider.ENA, source_type=SourceType.HTML, content=preliminary_html)
    call_command("process_raw_content")

    announcement.refresh_from_db()
    assert announcement.is_preliminary is False


def test_row_level_exception_does_not_block_other_rows():
    """
    Regression: one row's parser raising an unexpected exception must
    not abort the rest of the batch, and must not leave that row stuck
    retrying (and blocking every newer row queued behind it, since the
    queryset is oldest-first) on every subsequent run. Mirrors
    ingestion.fetchers.runner.run_fetcher's per-target isolation.
    """
    ena_html = (FIXTURES / "ena_page_sample.html").read_text(encoding="utf-8")
    bad_raw = _make_raw_content(provider=Provider.ENA, source_type=SourceType.HTML, content=ena_html)

    veolia_html = (FIXTURES / "veolia_telegram_page_sample.html").read_text(encoding="utf-8")
    good_raw = _make_raw_content(
        provider=Provider.VEOLIA_TELEGRAM, source_type=SourceType.TELEGRAM_TEXT, content=veolia_html
    )

    with mock.patch(
        "processing.management.commands.process_raw_content.parse_planned_section",
        side_effect=RuntimeError("simulated parser crash"),
    ):
        call_command("process_raw_content")  # must not raise

    bad_raw.refresh_from_db()
    good_raw.refresh_from_db()
    assert bad_raw.processed is True  # not retried forever
    assert good_raw.processed is True  # not blocked by the row queued before it
    assert not OutageAnnouncement.objects.filter(provider=Provider.ENA).exists()
    assert OutageAnnouncement.objects.filter(provider=Provider.VEOLIA_TELEGRAM).exists()
