import logging
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.utils import timezone

from ingestion.models import FetchStatus, RawContent

logger = logging.getLogger(__name__)


def get_latest_content(provider: str, reference: str) -> Optional[str]:
    """
    Return the content of the most recent successful fetch for this
    exact (provider, reference) pair, or None if there isn't one yet.
    Used by the runner to skip writing a duplicate row when a page
    hasn't changed since the last check — otherwise hourly polling over
    several days fills the table with near-identical HTML blobs.
    """
    return (
        RawContent.objects.filter(
            provider=provider, reference=reference, fetch_status=FetchStatus.OK
        )
        .order_by("-fetched_at")
        .values_list("content", flat=True)
        .first()
    )


def save_raw_content(
    *,
    provider: str,
    source_type: str,
    reference: str,
    fetch_status: str,
    content: str = "",
    error_message: str = "",
) -> RawContent:
    """
    Persist one fetch attempt: one DB row (source of truth for this
    attempt) plus, on success, a mirrored plain-text file on disk under
    settings.RAW_DUMP_DIRECTORY/<provider>/. The file dump is disposable
    and purely for convenient manual eyeballing while designing the
    Phase 1 parser; if it fails, we log and move on rather than losing
    the DB row.
    """
    raw = RawContent.objects.create(
        provider=provider,
        source_type=source_type,
        reference=reference,
        content=content,
        fetch_status=fetch_status,
        error_message=error_message,
    )

    if fetch_status == FetchStatus.OK and content:
        relative_path = _dump_to_file(provider=provider, raw_id=raw.id, content=content)
        if relative_path is not None:
            raw.dump_file_path = str(relative_path)
            raw.save(update_fields=["dump_file_path"])

    return raw


def _dump_to_file(*, provider: str, raw_id: int, content: str) -> Optional[Path]:
    directory = Path(settings.RAW_DUMP_DIRECTORY) / provider
    try:
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = timezone.now().strftime("%Y-%m-%dT%H-%M-%S")
        file_path = directory / f"{timestamp}_{raw_id}.html"
        file_path.write_text(content, encoding="utf-8")
        return file_path.relative_to(settings.RAW_DUMP_DIRECTORY)
    except OSError:
        logger.exception(
            "Failed to dump raw content to disk (provider=%s id=%s) — DB row is still saved.",
            provider, raw_id,
        )
        return None
