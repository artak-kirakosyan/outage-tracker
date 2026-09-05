from django.core.management.base import BaseCommand

from ingestion.fetchers.runner import run_fetcher
from ingestion.fetchers.veolia_telegram import VeoliaTelegramFetcher


class Command(BaseCommand):
    help = "Fetch Veolia's Telegram channel preview page and store it as raw content."

    def handle(self, *args, **options):
        run_fetcher(VeoliaTelegramFetcher())
