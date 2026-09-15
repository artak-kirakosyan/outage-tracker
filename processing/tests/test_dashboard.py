from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from accounts.models import Address, User
from common.enums import Channel, Region
from ingestion.models import FetchStatus, Provider, RawContent, SourceType
from notifications.models import NotificationLog, NotificationStatus
from processing.dashboard import EXTRACTION_FAILED_PREFIX, get_pipeline_health
from processing.models import OutageAnnouncement, OutageType, ParseStatus

pytestmark = pytest.mark.django_db


def _metric_map(groups):
    return {m.key: m for g in groups for m in g.metrics}


def _raw(*, provider=Provider.ENA, fetch_status=FetchStatus.OK, processed=False, **kwargs):
    return RawContent.objects.create(
        provider=provider,
        source_type=SourceType.HTML if provider == Provider.ENA else SourceType.TELEGRAM_TEXT,
        reference="https://example.test/",
        content=kwargs.pop("content", "x"),
        fetch_status=fetch_status,
        processed=processed,
        **kwargs,
    )


def _announcement(*, provider=Provider.ENA, parse_status=ParseStatus.OK, raw=None):
    raw = raw or _raw(provider=provider, processed=True)
    return OutageAnnouncement.objects.create(
        provider=provider,
        outage_type=OutageType.PLANNED if provider == Provider.ENA else OutageType.EMERGENCY,
        external_ref=f"ref-{OutageAnnouncement.objects.count() + 1}",
        parse_status=parse_status,
        first_seen_raw_content=raw,
        raw_address_text="somewhere",
    )


def test_fetch_failures_and_extraction_failures_are_counted():
    now = timezone.now()
    failed = _raw(fetch_status=FetchStatus.ERROR, error_message="503")
    extracted = _raw(
        processed=True,
        error_message=f"{EXTRACTION_FAILED_PREFIX} attenbody missing",
    )
    RawContent.objects.filter(pk__in=[failed.pk, extracted.pk]).update(fetched_at=now - timedelta(hours=2))

    metrics = _metric_map(get_pipeline_health())
    assert metrics["fetch_failures"].count == 1
    assert metrics["fetch_failures"].severity == "critical"
    assert metrics["extraction_failures"].count == 1
    assert "extraction=failed" in metrics["extraction_failures"].admin_url


def test_unprocessed_backlog_ignores_fresh_and_veolia_web():
    now = timezone.now()
    stale = _raw(provider=Provider.ENA, processed=False)
    fresh = _raw(provider=Provider.ENA, processed=False)
    web = _raw(provider=Provider.VEOLIA_WEB, processed=False)
    RawContent.objects.filter(pk=stale.pk).update(fetched_at=now - timedelta(hours=2))
    RawContent.objects.filter(pk=fresh.pk).update(fetched_at=now - timedelta(minutes=1))
    RawContent.objects.filter(pk=web.pk).update(fetched_at=now - timedelta(hours=5))

    metrics = _metric_map(get_pipeline_health())
    assert metrics["unprocessed_backlog"].count == 1


def test_parsing_and_notification_metrics():
    bad = _announcement(parse_status=ParseStatus.PARTIAL)
    veolia = _announcement(provider=Provider.VEOLIA_TELEGRAM, parse_status=ParseStatus.OK)
    # veolia has zero locations by default — should count
    user = User.objects.create(channel=Channel.TELEGRAM, external_id="1")
    address = Address.objects.create(
        user=user,
        region=Region.YEREVAN,
        district_or_city="Kentron",
        street="Abovyan",
        house_number=1,
    )
    NotificationLog.objects.create(
        user=user,
        address=address,
        outage_announcement=bad,
        status=NotificationStatus.FAILED,
    )

    metrics = _metric_map(get_pipeline_health())
    assert metrics["badly_parsed"].count == 1
    assert metrics["veolia_no_locations"].count == 1
    assert metrics["failed_notifications"].count == 1
    assert veolia.locations.count() == 0


def test_dead_subscriptions_counts_users_without_recent_matches():
    quiet = User.objects.create(channel=Channel.TELEGRAM, external_id="quiet")
    Address.objects.create(
        user=quiet,
        region=Region.YEREVAN,
        district_or_city="Kentron",
        street="Abovyan",
        house_number=2,
    )
    active = User.objects.create(channel=Channel.TELEGRAM, external_id="active")
    addr = Address.objects.create(
        user=active,
        region=Region.YEREVAN,
        district_or_city="Kentron",
        street="Tumanyan",
        house_number=3,
    )
    announcement = _announcement()
    NotificationLog.objects.create(
        user=active,
        address=addr,
        outage_announcement=announcement,
        status=NotificationStatus.SENT,
    )
    # User with no addresses is not an active subscription.
    User.objects.create(channel=Channel.TELEGRAM, external_id="empty")

    metrics = _metric_map(get_pipeline_health())
    assert metrics["dead_subscriptions"].count == 1


def test_extraction_failure_persists_error_message_for_dashboard():
    _raw(provider=Provider.ENA, content="<html><body>unexpected markup</body></html>")

    call_command("process_raw_content")

    raw = RawContent.objects.get()
    assert raw.processed is True
    assert raw.error_message.startswith(EXTRACTION_FAILED_PREFIX)
    metrics = _metric_map(get_pipeline_health())
    assert metrics["extraction_failures"].count == 1
