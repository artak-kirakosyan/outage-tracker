from django.core.management.base import BaseCommand

from ingestion.fetchers.ena import ENAFetcher
from ingestion.fetchers.runner import run_fetcher


class Command(BaseCommand):
    help = "Fetch ENA's outage info page and store it as raw content."

    def handle(self, *args, **options):
        run_fetcher(ENAFetcher())
