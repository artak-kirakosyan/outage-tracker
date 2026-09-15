from django.core.management.base import BaseCommand

from common.enums import Provider
from processing.models import OutageAnnouncement
from processing.persist_locations import replace_ena_locations


class Command(BaseCommand):
    help = (
        "Rebuild OutageLocation rows for every ENA announcement from "
        "raw_address_text (one-shot backfill / re-parse)."
    )

    def handle(self, *args, **options):
        qs = OutageAnnouncement.objects.filter(provider=Provider.ENA).order_by("id")
        announcements = 0
        locations = 0
        for announcement in qs:
            announcements += 1
            locations += replace_ena_locations(announcement)
        self.stdout.write(
            f"backfill_ena_locations: announcements={announcements} locations={locations}"
        )
