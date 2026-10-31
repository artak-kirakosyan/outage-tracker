import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone as dj_timezone

from common.enums import Provider
from processing.html_extract import extract_ena_planned_section, extract_veolia_telegram_posts
from processing.models import OutageAnnouncement, OutageLocation, ParseStatus
from processing.normalize import normalize_multiline
from processing.parsers.ai_parser import (
    is_ai_parser_available,
    parse_ena_day_block_ai,
    parse_ena_section_ai,
    parse_veolia_post_ai,
)
from processing.parsers.ena_locations import parse_ena_locations
from processing.parsers.ena_planned import parse_planned_section
from processing.parsers.veolia_telegram import parse_post
from processing.persist_locations import locations_from_parsed

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Re-run parsing on failed, partial, or zero-location OutageAnnouncement rows "
        "using the AI parser (with regex fallback)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Re-parse ALL announcements, not just failed/partial/empty ones.",
        )
        parser.add_argument(
            "--provider",
            choices=["ena", "veolia_telegram"],
            help="Filter re-parsing by provider.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of announcements to reprocess.",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=4.0,
            help="Delay in seconds between requests to avoid rate limits (default: 4.0s for 15 RPM free tier). Set to 0 to disable.",
        )

    def handle(self, *args, **options):
        delay = options["delay"]
        if delay > 0:
            settings.GEMINI_REQUEST_DELAY_SECONDS = max(
                getattr(settings, "GEMINI_REQUEST_DELAY_SECONDS", 0.0),
                delay,
            )

        if not is_ai_parser_available():
            self.stdout.write(
                self.style.WARNING(
                    "Warning: AI parser is not enabled or GEMINI_API_KEY is not set. "
                    "Running with regex parsers only."
                )
            )

        qs = OutageAnnouncement.objects.annotate(loc_count=Count("locations"))

        if options["provider"]:
            qs = qs.filter(provider=options["provider"])

        if not options["all"]:
            # Default: announcements that failed, had partial status, had 0 locations,
            # or have locations marked unparsed
            unparsed_ann_ids = OutageLocation.objects.filter(kind="unparsed").values_list("announcement_id", flat=True)
            qs = qs.filter(
                Q(parse_status__in=[ParseStatus.FAILED, ParseStatus.PARTIAL])
                | Q(loc_count=0)
                | Q(id__in=unparsed_ann_ids)
            )

        qs = qs.order_by("id")
        if options["limit"]:
            qs = qs[: options["limit"]]

        total = qs.count()
        self.stdout.write(f"Found {total} candidate announcements to reprocess.")

        stats = {
            "total": total,
            "veolia_processed": 0,
            "ena_processed": 0,
            "upgraded_to_ok": 0,
            "locations_created": 0,
            "still_failed": 0,
        }

        for ann in qs:
            try:
                with transaction.atomic():
                    if ann.provider == Provider.VEOLIA_TELEGRAM:
                        self._reprocess_veolia(ann, stats)
                    elif ann.provider == Provider.ENA:
                        self._reprocess_ena(ann, stats)
            except Exception as exc:
                logger.exception("Error reprocessing announcement id=%s: %s", ann.id, exc)
                self.stdout.write(self.style.ERROR(f"Error on announcement {ann.id}: {exc}"))

            if delay > 0:
                time.sleep(delay)

        self.stdout.write(self.style.SUCCESS(f"Reprocessing completed: {stats}"))

    def _reprocess_veolia(self, ann: OutageAnnouncement, stats: dict):
        stats["veolia_processed"] += 1
        raw = ann.first_seen_raw_content
        if not raw or not raw.content:
            stats["still_failed"] += 1
            return

        posts = dict(extract_veolia_telegram_posts(raw.content))
        post_text = posts.get(ann.external_ref)
        if not post_text:
            stats["still_failed"] += 1
            return

        year = dj_timezone.localtime(raw.fetched_at).year if raw.fetched_at else dj_timezone.now().year

        result = None
        if is_ai_parser_available():
            try:
                result = parse_veolia_post_ai(post_text, year=year)
            except Exception as exc:
                logger.warning("AI parse failed for %s (%s); trying regex", ann.external_ref, exc)

        if result is None:
            result = parse_post(post_text, year=year)

        # Update announcement fields
        old_status = ann.parse_status
        ann.outage_type = result.outage_type
        ann.marz = result.marz
        ann.district_or_city = result.district_or_city
        ann.starts_at = dj_timezone.make_aware(result.starts_at) if result.starts_at and dj_timezone.is_naive(result.starts_at) else result.starts_at
        ann.ends_at = dj_timezone.make_aware(result.ends_at) if result.ends_at and dj_timezone.is_naive(result.ends_at) else result.ends_at
        ann.raw_heading_text = result.raw_heading_text or ann.raw_heading_text
        ann.raw_address_text = result.raw_address_text or ann.raw_address_text
        ann.parse_status = result.parse_status
        ann.save()

        # Rebuild locations
        ann.locations.all().delete()
        if result.locations:
            loc_rows = locations_from_parsed(ann, result.locations)
            OutageLocation.objects.bulk_create(loc_rows)
            stats["locations_created"] += len(loc_rows)

        if ann.parse_status == ParseStatus.OK:
            stats["upgraded_to_ok"] += 1
            self.stdout.write(f"Veolia {ann.external_ref} -> OK ({len(result.locations)} locations)")
        else:
            stats["still_failed"] += 1
            self.stdout.write(f"Veolia {ann.external_ref} -> {ann.parse_status}")

    def _reprocess_ena(self, ann: OutageAnnouncement, stats: dict):
        stats["ena_processed"] += 1
        # If we have address text, re-decompose locations
        addr_text = ann.raw_address_text
        if not addr_text and ann.first_seen_raw_content:
            section = extract_ena_planned_section(ann.first_seen_raw_content.content)
            if section:
                addr_text = normalize_multiline(section)

        if not addr_text:
            stats["still_failed"] += 1
            return

        parsed_locs = parse_ena_locations(addr_text)
        ann.locations.all().delete()
        if parsed_locs:
            loc_rows = locations_from_parsed(ann, parsed_locs)
            OutageLocation.objects.bulk_create(loc_rows)
            stats["locations_created"] += len(loc_rows)
            if ann.parse_status != ParseStatus.OK:
                ann.parse_status = ParseStatus.OK
                ann.save(update_fields=["parse_status"])
                stats["upgraded_to_ok"] += 1
            self.stdout.write(f"ENA {ann.external_ref[:16]} -> OK ({len(loc_rows)} locations)")
        else:
            stats["still_failed"] += 1
