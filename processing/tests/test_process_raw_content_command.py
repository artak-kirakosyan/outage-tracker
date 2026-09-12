from pathlib import Path

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


def test_processes_ena_page_into_announcements_without_locations():
    html = (FIXTURES / "ena_page_sample.html").read_text(encoding="utf-8")
    _make_raw_content(provider=Provider.ENA, source_type=SourceType.HTML, content=html)

    call_command("process_raw_content")

    announcements = OutageAnnouncement.objects.filter(provider=Provider.ENA)
    assert announcements.count() > 0
    # ENA planned stays shallow in v1 -- no per-location decomposition.
    assert OutageLocation.objects.filter(announcement__provider=Provider.ENA).count() == 0
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
    _make_raw_content(
        provider=Provider.ENA, source_type=SourceType.HTML, content="<html><body>unexpected markup</body></html>"
    )

    call_command("process_raw_content")  # must not raise

    assert OutageAnnouncement.objects.count() == 0
    assert RawContent.objects.get().processed is True
