"""
external_ref computation for OutageAnnouncement idempotency (see
docs/phase-1-processing-plan.md §6). Kept separate from models.py so
persistence and "what makes two announcements the same" stay
independently testable.

Veolia doesn't need a function here -- its external_ref is just the
real Telegram data-post id returned by html_extract.extract_veolia_telegram_posts,
used directly.
"""
import hashlib

from processing.parsers.ena_planned import EnaPlannedAnnouncement


def ena_external_ref(announcement: EnaPlannedAnnouncement) -> str:
    """
    ENA's planned block has no natural per-announcement id, so the ref
    is a hash of the fields that define "the same announcement": if ENA
    edits an existing block's address list, the hash changes and a new
    row is created rather than the old one being updated in place --
    accepted as a known v1 limitation (see the plan doc).
    """
    parts = [
        str(announcement.date),
        announcement.raw_heading_text,
        str(announcement.starts_at),
        str(announcement.ends_at),
        announcement.raw_address_text,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
