from django.core.management.base import BaseCommand

from ingestion.fetchers.runner import run_fetcher
from ingestion.fetchers.veolia_web import VeoliaWebFetcher


class Command(BaseCommand):
    help = "Fetch Veolia's 3-page outage listing and store each page as raw content."

    def handle(self, *args, **options):
        run_fetcher(VeoliaWebFetcher())
