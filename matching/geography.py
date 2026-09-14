"""
Canonicalizes the inflected/genitive marz text OutageAnnouncement.marz
stores (parsed verbatim from ENA/Veolia prose -- see processing/parsers/*)
into the same values common.enums.Region uses, so an Address.region can
be compared directly against an announcement's marz.

Needs fewer entries than a general Armenian-inflection system would:
both parsers already store Yerevan canonically ("Երևան"), only real
marzes come out genitive. Add an entry here each time common.enums.Region
grows to cover a new marz -- see
docs/phase-1.3-users-matching-notifications-plan.md.
"""
from common.enums import Region

_MARZ_TO_REGION: dict[str, Region] = {
    "Երևան": Region.YEREVAN,
    "Արարատի": Region.ARARAT,
}

_REGION_TO_MARZ_VALUES: dict[str, list[str]] = {}
for _raw_marz, _region in _MARZ_TO_REGION.items():
    _REGION_TO_MARZ_VALUES.setdefault(_region.value, []).append(_raw_marz)


def canonicalize_marz(marz: str | None) -> Region | None:
    """
    Returns the Region an announcement's raw marz text corresponds to,
    or None if it's not a region with address-matching support yet.
    """
    if not marz:
        return None
    return _MARZ_TO_REGION.get(marz.strip())


def marz_values_for_region(region: str) -> list[str]:
    """The raw marz strings (as OutageAnnouncement.marz stores them)
    that canonicalize to the given region."""
    return _REGION_TO_MARZ_VALUES.get(region, [])
