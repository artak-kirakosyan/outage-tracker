import logging

from ingestion.fetchers.base import BaseFetcher, FetchTarget
from ingestion.models import Provider, SourceType

logger = logging.getLogger(__name__)


class ENAFetcher(BaseFetcher):
    """
    ENA (electricity). This single info page is where the old repo
    found outage notices; it's NOT yet confirmed whether both planned
    *and* emergency outages live here, or whether emergency ones need a
    separate URL — that's an open item for the Phase 0.5 data review
    (see docs/phase-0.5-plan.md). Phase 0.5 just fetches whatever is
    here, verbatim, and we'll find out once we can look at a few days
    of samples.

    Note: ENA's page is an ASP.NET WebForms app whose full HTML contains
    session-scoped tokens (__VIEWSTATE, __EVENTVALIDATION, etc.) that
    change on *every* request even if the outage content is unchanged.
    Storing and comparing the full HTML would defeat get_latest_content()'s
    deduplication and write a new RawContent row on every scheduled run.
    Instead, fetch_one() extracts and returns only the attenbody section
    text so that identical outage content produces an identical stored
    string, and the runner's byte-comparison correctly skips unchanged runs.
    """

    provider = Provider.ENA
    source_type = SourceType.HTML
    URL = "https://www.ena.am/Info.aspx?id=5&lang=1"

    def fetch_targets(self) -> list[FetchTarget]:
        return [FetchTarget(reference=self.URL)]

    def fetch_one(self, target: FetchTarget) -> str:
        from ingestion.fetchers.http import fetch_page_text
        from processing.html_extract import extract_ena_planned_section

        html = fetch_page_text(target.reference)
        section = extract_ena_planned_section(html)
        if section is None:
            # The attenbody element wasn't found (markup change?).
            # Return the full HTML so the runner still saves a row and
            # process_raw_content can emit an extraction_failed message
            # rather than silently losing the fetch.
            logger.warning(
                "ENAFetcher: attenbody section not found in response from %s — "
                "storing full HTML so the failure is visible in the admin.",
                target.reference,
            )
            return html
        return section
