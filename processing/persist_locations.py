"""Shared helpers for persisting ParsedLocation rows onto OutageAnnouncement."""
from __future__ import annotations

from processing.address_grammar import ParsedLocation
from processing.models import OutageAnnouncement, OutageLocation


def locations_from_parsed(
    announcement: OutageAnnouncement, parsed: list[ParsedLocation]
) -> list[OutageLocation]:
    return [
        OutageLocation(
            announcement=announcement,
            raw_fragment=loc.raw_fragment,
            kind=loc.kind.value,
            street=loc.street,
            house_low=loc.house_low,
            house_low_sub=loc.house_low_sub,
            house_high=loc.house_high,
            house_high_sub=loc.house_high_sub,
            parity=loc.parity.value,
            is_matchable=loc.is_matchable,
            locality=loc.locality or "",
            qualifier=loc.qualifier.value if loc.qualifier else "",
        )
        for loc in parsed
    ]


def replace_ena_locations(announcement: OutageAnnouncement) -> int:
    """
    Delete existing locations and recreate from raw_address_text.
    Returns the number of locations created.
    """
    from processing.parsers.ena_locations import parse_ena_locations

    announcement.locations.all().delete()
    parsed = parse_ena_locations(announcement.raw_address_text or "")
    rows = locations_from_parsed(announcement, parsed)
    OutageLocation.objects.bulk_create(rows)
    return len(rows)
