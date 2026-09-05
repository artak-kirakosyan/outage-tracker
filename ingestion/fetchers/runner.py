import logging

from ingestion.fetchers.base import BaseFetcher
from ingestion.fetchers.http import FetchError
from ingestion.models import FetchStatus
from ingestion.storage import get_latest_content, save_raw_content

logger = logging.getLogger(__name__)


def run_fetcher(fetcher: BaseFetcher) -> dict:
    """
    Runs a fetcher end-to-end: fetch every target, save a RawContent row
    per target that's new or error, and never let one target's failure
    stop the others (matters for Veolia's 3-page site). Targets whose
    content is byte-identical to the last successful fetch are skipped
    (see storage.get_latest_content) to avoid filling the table with
    duplicate rows during long polling runs. Returns a small summary
    dict for the calling management command to log/print.
    """
    targets = fetcher.fetch_targets()
    ok_count = 0
    unchanged_count = 0
    error_count = 0

    for target in targets:
        try:
            content = fetcher.fetch_one(target)
        except FetchError as exc:
            logger.error("Fetch failed for %s (%s): %s", fetcher.provider, target.reference, exc)
            save_raw_content(
                provider=fetcher.provider,
                source_type=fetcher.source_type,
                reference=target.reference,
                fetch_status=FetchStatus.ERROR,
                error_message=str(exc),
            )
            error_count += 1
            continue

        if get_latest_content(fetcher.provider, target.reference) == content:
            logger.info("Unchanged since last fetch, skipping: %s (%s)", fetcher.provider, target.reference)
            unchanged_count += 1
            continue

        save_raw_content(
            provider=fetcher.provider,
            source_type=fetcher.source_type,
            reference=target.reference,
            content=content,
            fetch_status=FetchStatus.OK,
        )
        ok_count += 1
        logger.info("Fetched OK (new/changed content): %s (%s)", fetcher.provider, target.reference)

    summary = {
        "provider": str(fetcher.provider),
        "targets": len(targets),
        "ok": ok_count,
        "unchanged": unchanged_count,
        "error": error_count,
    }
    logger.info("Run summary: %s", summary)
    return summary
