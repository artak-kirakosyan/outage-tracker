from ingestion.fetchers.base import BaseFetcher, FetchTarget
from ingestion.models import Provider, SourceType


class VeoliaWebFetcher(BaseFetcher):
    """
    Veolia's (water) outage listing is paginated across 3 pages on their
    site. Each page is stored as its own raw row — simplest option for
    Phase 0.5; revisit concatenating them into one row if that turns out
    cleaner once we've seen real data (see plan doc).
    """

    provider = Provider.VEOLIA_WEB
    source_type = SourceType.HTML
    BASE_URL = "https://interactive.vjur.am/?ajax=list-post"
    PAGES = (1, 2, 3)

    def fetch_targets(self) -> list[FetchTarget]:
        return [FetchTarget(reference=f"{self.BASE_URL}&page={page}") for page in self.PAGES]
