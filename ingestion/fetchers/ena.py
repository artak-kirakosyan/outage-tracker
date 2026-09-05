from ingestion.fetchers.base import BaseFetcher, FetchTarget
from ingestion.models import Provider, SourceType


class ENAFetcher(BaseFetcher):
    """
    ENA (electricity). This single info page is where the old repo
    found outage notices; it's NOT yet confirmed whether both planned
    *and* emergency outages live here, or whether emergency ones need a
    separate URL — that's an open item for the Phase 0.5 data review
    (see docs/phase-0.5-plan.md). Phase 0.5 just fetches whatever is
    here, verbatim, and we'll find out once we can look at a few days
    of samples.
    """

    provider = Provider.ENA
    source_type = SourceType.HTML
    URL = "https://www.ena.am/Info.aspx?id=5&lang=1"

    def fetch_targets(self) -> list[FetchTarget]:
        return [FetchTarget(reference=self.URL)]
