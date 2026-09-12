import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone as dj_timezone

from ingestion.models import FetchStatus, Provider, RawContent
from processing.html_extract import extract_ena_planned_section, extract_veolia_telegram_posts
from processing.idempotency import ena_external_ref
from processing.models import OutageAnnouncement, OutageLocation, OutageType
from processing.parsers.ena_planned import parse_planned_section
from processing.parsers.veolia_telegram import parse_post

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Parse unprocessed RawContent rows (ena, veolia_telegram) into OutageAnnouncement/OutageLocation."

    def handle(self, *args, **options):
        queryset = RawContent.objects.filter(
            processed=False,
            fetch_status=FetchStatus.OK,
            provider__in=[Provider.ENA, Provider.VEOLIA_TELEGRAM],
        ).order_by("fetched_at")

        summary = {
            "rows": 0,
            "announcements_created": 0,
            "announcements_touched": 0,
            "locations_created": 0,
            "extraction_failed": 0,
            "row_errors": 0,
        }

        for raw in queryset:
            summary["rows"] += 1
            try:
                with transaction.atomic():
                    if raw.provider == Provider.ENA:
                        self._process_ena(raw, summary)
                    else:
                        self._process_veolia(raw, summary)
                    raw.processed = True
                    raw.save(update_fields=["processed"])
            except Exception:
                # The queryset is oldest-first and re-run every tick, so
                # leaving a row that raises as processed=False would
                # have it fail the same way forever, permanently
                # blocking every newer row queued behind it. Mirrors
                # ingestion.fetchers.runner.run_fetcher's "one target's
                # failure must not lose the others" isolation, and the
                # extraction_failed case just below: log it, mark the
                # row processed so it isn't retried, move on to the
                # next row. The row's own transaction has already
                # rolled back by this point, so this save is separate
                # and outside it.
                logger.exception(
                    "Unexpected error processing RawContent id=%s (provider=%s); marking processed to avoid blocking later rows.",
                    raw.id, raw.provider,
                )
                summary["row_errors"] += 1
                raw.processed = True
                raw.save(update_fields=["processed"])

        self.stdout.write(f"process_raw_content summary: {summary}")
        logger.info("process_raw_content summary: %s", summary)

    def _process_ena(self, raw: RawContent, summary: dict) -> None:
        section = extract_ena_planned_section(raw.content)
        if section is None:
            # An OK-status fetch that yields nothing usable is a real
            # signal (markup change, wrong id guess), not a quiet no-op.
            logger.error("ENA planned section ('attenbody') not found in RawContent id=%s.", raw.id)
            summary["extraction_failed"] += 1
            return

        year = dj_timezone.localtime(raw.fetched_at).year
        for item in parse_planned_section(section, year=year):
            obj, created = OutageAnnouncement.objects.get_or_create(
                provider=Provider.ENA,
                external_ref=ena_external_ref(item),
                defaults=dict(
                    outage_type=OutageType.PLANNED,
                    is_preliminary=item.is_preliminary,
                    marz=item.marz_or_yerevan,
                    district_or_city=item.district,
                    starts_at=_make_aware(item.starts_at),
                    ends_at=_make_aware(item.ends_at),
                    raw_heading_text=item.raw_heading_text,
                    raw_address_text=item.raw_address_text,
                    parse_status=item.parse_status,
                    first_seen_raw_content=raw,
                ),
            )
            if created:
                summary["announcements_created"] += 1
            else:
                summary["announcements_touched"] += 1
                update_fields = ["last_seen_at"]
                # is_preliminary is deliberately not part of
                # ena_external_ref (see its docstring), so this is the
                # one field a re-sighting of the same hash can still
                # legitimately change: ENA re-lists an unchanged
                # day-block as confirmed after first showing it as
                # preliminary. Only ever downgrade True->False, never
                # the reverse.
                if obj.is_preliminary and not item.is_preliminary:
                    obj.is_preliminary = False
                    update_fields.append("is_preliminary")
                obj.save(update_fields=update_fields)

    def _process_veolia(self, raw: RawContent, summary: dict) -> None:
        posts = extract_veolia_telegram_posts(raw.content)
        if not posts:
            logger.error("No Telegram posts extracted from RawContent id=%s.", raw.id)
            summary["extraction_failed"] += 1
            return

        year = dj_timezone.localtime(raw.fetched_at).year
        for external_ref, text in posts:
            result = parse_post(text, year=year)
            obj, created = OutageAnnouncement.objects.get_or_create(
                provider=Provider.VEOLIA_TELEGRAM,
                external_ref=external_ref,
                defaults=dict(
                    outage_type=OutageType.EMERGENCY,
                    is_preliminary=False,
                    marz=result.marz,
                    district_or_city=result.district_or_city,
                    starts_at=_make_aware(result.starts_at),
                    ends_at=_make_aware(result.ends_at),
                    raw_heading_text=result.raw_heading_text,
                    raw_address_text=result.raw_address_text,
                    parse_status=result.parse_status,
                    first_seen_raw_content=raw,
                ),
            )
            if created:
                summary["announcements_created"] += 1
                # Locations are only ever created alongside a new
                # announcement -- a repeat sighting of the same post
                # (same external_ref) just bumps last_seen_at below, it
                # never re-derives or duplicates the location rows.
                locations = [
                    OutageLocation(
                        announcement=obj,
                        raw_fragment=loc.raw_fragment,
                        kind=loc.kind.value,
                        street=loc.street,
                        house_low=loc.house_low,
                        house_low_sub=loc.house_low_sub,
                        house_high=loc.house_high,
                        house_high_sub=loc.house_high_sub,
                        parity=loc.parity.value,
                        is_matchable=loc.is_matchable,
                    )
                    for loc in result.locations
                ]
                OutageLocation.objects.bulk_create(locations)
                summary["locations_created"] += len(locations)
            else:
                summary["announcements_touched"] += 1
                obj.save(update_fields=["last_seen_at"])


def _make_aware(naive_datetime):
    if naive_datetime is None:
        return None
    return dj_timezone.make_aware(naive_datetime)
