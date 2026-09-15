"""
Pipeline-health aggregates for the Django admin index.

Surfaces silent failures across Fetch → Parse → Match → Notify without
extra infra (Grafana, etc.). Counts are cheap ORM aggregates over
existing tables — see templates/admin/index.html.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from common.enums import Provider
from ingestion.models import FetchStatus, RawContent
from notifications.models import NotificationLog, NotificationStatus
from processing.models import OutageAnnouncement, ParseStatus

# Written onto RawContent.error_message (fetch_status stays OK) when the
# HTML/Telegram extractor finds nothing usable — see process_raw_content.
EXTRACTION_FAILED_PREFIX = "extraction_failed:"

PROCESSABLE_PROVIDERS = (Provider.ENA, Provider.VEOLIA_TELEGRAM)


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    count: int
    detail: str
    severity: str  # "ok" | "warn" | "critical"
    admin_url: str | None = None


@dataclass(frozen=True)
class MetricGroup:
    title: str
    metrics: list[Metric]


def extraction_failed_message(reason: str) -> str:
    return f"{EXTRACTION_FAILED_PREFIX} {reason}"


def _changelist(app_label: str, model_name: str, **params) -> str:
    url = reverse(f"admin:{app_label}_{model_name}_changelist")
    if params:
        return f"{url}?{urlencode(params)}"
    return url


def _severity(count: int, *, warn_at: int = 1, critical_at: int | None = None) -> str:
    if count <= 0:
        return "ok"
    if critical_at is not None and count >= critical_at:
        return "critical"
    if count >= warn_at:
        return "warn" if critical_at is not None else "critical"
    return "ok"


def get_pipeline_health() -> list[MetricGroup]:
    now = timezone.now()
    ago_24h = now - timedelta(hours=24)
    ago_48h = now - timedelta(hours=48)
    backlog_cutoff = now - timedelta(minutes=10)
    dead_months = int(getattr(settings, "DEAD_SUBSCRIPTION_MONTHS", 3))
    dead_cutoff = now - timedelta(days=30 * dead_months)

    fetch_24h = RawContent.objects.filter(
        fetch_status=FetchStatus.ERROR, fetched_at__gte=ago_24h
    ).count()
    fetch_48h = RawContent.objects.filter(
        fetch_status=FetchStatus.ERROR, fetched_at__gte=ago_48h
    ).count()

    extraction_24h = RawContent.objects.filter(
        fetched_at__gte=ago_24h,
        error_message__startswith=EXTRACTION_FAILED_PREFIX,
    ).count()
    extraction_48h = RawContent.objects.filter(
        fetched_at__gte=ago_48h,
        error_message__startswith=EXTRACTION_FAILED_PREFIX,
    ).count()

    backlog = RawContent.objects.filter(
        processed=False,
        fetch_status=FetchStatus.OK,
        provider__in=PROCESSABLE_PROVIDERS,
        fetched_at__lt=backlog_cutoff,
    ).count()

    badly_parsed = OutageAnnouncement.objects.filter(
        parse_status__in=[ParseStatus.PARTIAL, ParseStatus.FAILED],
        first_seen_at__gte=ago_48h,
    ).count()
    badly_parsed_partial = OutageAnnouncement.objects.filter(
        parse_status=ParseStatus.PARTIAL, first_seen_at__gte=ago_48h
    ).count()
    badly_parsed_failed = OutageAnnouncement.objects.filter(
        parse_status=ParseStatus.FAILED, first_seen_at__gte=ago_48h
    ).count()

    veolia_no_locations = (
        OutageAnnouncement.objects.filter(
            provider=Provider.VEOLIA_TELEGRAM,
            first_seen_at__gte=ago_48h,
        )
        .annotate(loc_count=Count("locations"))
        .filter(loc_count=0)
        .count()
    )

    failed_notifications = NotificationLog.objects.filter(
        status=NotificationStatus.FAILED,
        created_at__gte=ago_48h,
    ).count()

    # "Active" = has at least one registered address. "Dead" = no
    # NotificationLog (match/notify attempt) since the cutoff — including
    # users who never matched at all if they registered before the cutoff.
    dead_subscriptions = (
        User.objects.filter(addresses__isnull=False)
        .annotate(
            recent_notes=Count(
                "notifications",
                filter=Q(notifications__created_at__gte=dead_cutoff),
            )
        )
        .filter(recent_notes=0)
        .distinct()
        .count()
    )

    return [
        MetricGroup(
            title="Ingestion health",
            metrics=[
                Metric(
                    key="fetch_failures",
                    label="Fetch failures",
                    count=fetch_24h,
                    detail=f"{fetch_24h} in 24h · {fetch_48h} in 48h",
                    severity=_severity(fetch_24h),
                    admin_url=_changelist(
                        "ingestion", "rawcontent", fetch_status__exact=FetchStatus.ERROR
                    ),
                ),
                Metric(
                    key="extraction_failures",
                    label="HTML / Telegram extraction failures",
                    count=extraction_24h,
                    detail=f"{extraction_24h} in 24h · {extraction_48h} in 48h",
                    severity=_severity(extraction_24h),
                    admin_url=_changelist("ingestion", "rawcontent", extraction="failed"),
                ),
                Metric(
                    key="unprocessed_backlog",
                    label="Unprocessed backlog (>10m)",
                    count=backlog,
                    detail="OK fetches for ENA / Veolia Telegram still unprocessed",
                    severity=_severity(backlog),
                    admin_url=_changelist(
                        "ingestion",
                        "rawcontent",
                        processed__exact=0,
                        fetch_status__exact=FetchStatus.OK,
                    ),
                ),
            ],
        ),
        MetricGroup(
            title="Parsing quality",
            metrics=[
                Metric(
                    key="badly_parsed",
                    label="Badly parsed outages",
                    count=badly_parsed,
                    detail=(
                        f"{badly_parsed_partial} partial · {badly_parsed_failed} failed "
                        f"(first seen in 48h)"
                    ),
                    severity=_severity(badly_parsed),
                    admin_url=_changelist(
                        "processing", "outageannouncement", parse_health="bad"
                    ),
                ),
                Metric(
                    key="veolia_no_locations",
                    label="Veolia announcements with 0 locations",
                    count=veolia_no_locations,
                    detail="First seen in 48h — address grammar likely drifted",
                    severity=_severity(veolia_no_locations),
                    admin_url=_changelist(
                        "processing",
                        "outageannouncement",
                        provider__exact=Provider.VEOLIA_TELEGRAM,
                        locations="none",
                    ),
                ),
            ],
        ),
        MetricGroup(
            title="Matching & notifications",
            metrics=[
                Metric(
                    key="failed_notifications",
                    label="Failed notifications",
                    count=failed_notifications,
                    detail="Delivery failures in the last 48h",
                    severity=_severity(failed_notifications),
                    admin_url=_changelist(
                        "notifications",
                        "notificationlog",
                        status__exact=NotificationStatus.FAILED,
                    ),
                ),
                Metric(
                    key="dead_subscriptions",
                    label="Unmatched / quiet users",
                    count=dead_subscriptions,
                    detail=(
                        f"Users with addresses and no match/notify in {dead_months} months"
                    ),
                    severity=_severity(dead_subscriptions, warn_at=1, critical_at=50),
                    admin_url=_changelist("accounts", "user"),
                ),
            ],
        ),
    ]
