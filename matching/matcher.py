"""
Pure address <-> outage-announcement matching, kept independent of any
persistence -- see notifications/compute.py for turning a Match into a
logged NotificationLog row, and
docs/phase-1.3-users-matching-notifications-plan.md for the design
decisions behind the two confidence levels below.
"""
import dataclasses
import datetime

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from accounts.models import Address
from matching.geography import marz_values_for_region
from processing.address_grammar import LocationKind, Parity
from processing.models import OutageAnnouncement, OutageLocation, ParseStatus


@dataclasses.dataclass(frozen=True)
class Match:
    address: Address
    announcement: OutageAnnouncement
    # "high": a Veolia-style structured OutageLocation match (street +
    # house-number range/parity). "low": an ENA-style substring match
    # against raw_address_text -- street-name granularity only, no
    # house-number check, so it over-matches by design (see the plan
    # doc's note on ENA's precision gap).
    confidence: str


def find_matches_for_address(address: Address) -> list[Match]:
    marz_values = marz_values_for_region(address.region)
    if not marz_values:
        return []

    matches = []
    for announcement in _relevant_announcements(marz_values):
        locations = list(announcement.locations.all())
        if locations:
            if any(_location_matches_address(loc, address) for loc in locations):
                matches.append(Match(address=address, announcement=announcement, confidence="high"))
        elif _raw_text_matches_address(announcement, address):
            matches.append(Match(address=address, announcement=announcement, confidence="low"))
    return matches


def _relevant_announcements(marz_values: list[str]):
    """
    OutageAnnouncement is append-only and never pruned (same as
    RawContent), so an unbounded scan of it gets slower forever as the
    table grows, independent of how many addresses or announcements are
    actually still relevant. Bounded by time instead of a "seen it
    already" flag, since a brand-new Address still needs to be checked
    against an outage that's still ongoing, however old the row is.

    Two cases:
      - ends_at is set: still a candidate until MATCH_END_GRACE_HOURS
        after it ends (so an address registered right as an outage
        wraps up still sees it).
      - ends_at is missing (some "partial" parses never get a
        structured end time -- see
        processing/parsers/ena_planned.py's no-time-match branch):
        fall back to last_seen_at recency within
        MATCH_STALE_WITHOUT_END_DAYS, since there's no real end time to
        check against.
    """
    now = timezone.now()
    end_cutoff = now - datetime.timedelta(hours=settings.MATCH_END_GRACE_HOURS)
    stale_cutoff = now - datetime.timedelta(days=settings.MATCH_STALE_WITHOUT_END_DAYS)

    return (
        OutageAnnouncement.objects.filter(marz__in=marz_values)
        # A failed parse's raw_address_text is the whole unparsed block,
        # not a real address list -- matching against it would be noise,
        # not signal. See processing/parsers/ena_planned.py's "failed"
        # branch.
        .exclude(parse_status=ParseStatus.FAILED)
        .filter(
            Q(ends_at__isnull=False, ends_at__gte=end_cutoff)
            | Q(ends_at__isnull=True, last_seen_at__gte=stale_cutoff)
        )
        .prefetch_related("locations")
    )


def _normalize_street(value: str) -> str:
    return " ".join(value.split()).lower()


def _raw_text_matches_address(announcement: OutageAnnouncement, address: Address) -> bool:
    street = _normalize_street(address.street)
    if not street:
        return False
    return street in _normalize_street(announcement.raw_address_text or "")


def _location_matches_address(location: OutageLocation, address: Address) -> bool:
    if not location.is_matchable or location.kind == LocationKind.UNPARSED:
        return False
    if not location.street:
        return False
    if _normalize_street(location.street) != _normalize_street(address.street):
        return False

    if location.kind in (LocationKind.WHOLE_AREA, LocationKind.WHOLE_STREET):
        return True
    if location.kind == LocationKind.STREET_NUMBER_RANGE:
        # These numbers are STREET numbers (numbered-street areas like
        # Նոր Արեշ), not house numbers -- see
        # processing/address_grammar.py's module docstring. Not
        # something a resident's own house number can match against.
        return False
    if location.kind == LocationKind.STREET_RANGE:
        return _house_number_matches(address, location)
    return False


def _house_number_matches(address: Address, location: OutageLocation) -> bool:
    number = address.house_number
    if location.house_low is None or location.house_high is None:
        return False
    if not (location.house_low <= number <= location.house_high):
        return False
    if location.parity == Parity.EVEN and number % 2 != 0:
        return False
    if location.parity == Parity.ODD and number % 2 == 0:
        return False

    # Sub-number tie-break at range boundaries only -- an interior
    # number always matches regardless of sub. This follows the
    # "implicit /1 floor" rule from docs/data-patterns.md §4, which is
    # flagged there as our own assumption, not provider-confirmed. If
    # either side's sub isn't a plain integer (e.g. a letter suffix
    # like "Ա"), we don't reject the match -- leaning toward over-
    # rather than under-matching, consistent with the ENA raw-text path.
    address_sub = _sub_as_int(address.house_number_sub)
    if number == location.house_low:
        bound_sub = _sub_as_int(location.house_low_sub)
        if bound_sub is not None and address_sub is not None and address_sub < bound_sub:
            return False
    if number == location.house_high:
        bound_sub = _sub_as_int(location.house_high_sub)
        if bound_sub is not None and address_sub is not None and address_sub > bound_sub:
            return False
    return True


def _sub_as_int(sub: str | None) -> int | None:
    if not sub:
        return None
    try:
        return int(sub)
    except ValueError:
        return None
