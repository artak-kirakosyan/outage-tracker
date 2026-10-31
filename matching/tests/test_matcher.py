import datetime

import pytest
from django.utils import timezone

from accounts.models import Address, User
from common.enums import Confidence, Region
from ingestion.models import FetchStatus, Provider, RawContent, SourceType
from matching.matcher import find_matches_for_address, match_confidence_for_announcement
from processing.address_grammar import LocationKind, Parity
from processing.models import OutageAnnouncement, OutageLocation, OutageType, ParseStatus

pytestmark = pytest.mark.django_db


def _raw_content(provider=Provider.VEOLIA_TELEGRAM):
    return RawContent.objects.create(
        provider=provider, source_type=SourceType.TELEGRAM_TEXT,
        reference="https://t.me/s/VeoliaJur", fetch_status=FetchStatus.OK, content="x",
    )


def _address(**kwargs):
    user = User.objects.create(external_id=kwargs.pop("external_id", "1"))
    defaults = dict(region=Region.YEREVAN, district_or_city="Kentron", street="Tumanyan", house_number=10)
    defaults.update(kwargs)
    return Address.objects.create(user=user, **defaults)


def _announcement(marz="Երևան", raw_address_text="", external_ref="ref-1",
                   provider=Provider.VEOLIA_TELEGRAM, parse_status=ParseStatus.OK, ends_at=None):
    return OutageAnnouncement.objects.create(
        provider=provider, outage_type=OutageType.EMERGENCY, marz=marz,
        raw_address_text=raw_address_text, external_ref=external_ref,
        parse_status=parse_status, ends_at=ends_at, first_seen_raw_content=_raw_content(provider),
    )


def _backdate_last_seen(announcement, when):
    # last_seen_at is auto_now=True, so Model.save() always overwrites
    # it to "now" -- .update() bypasses save() entirely and is the
    # standard way to set an auto_now field to an arbitrary value in a
    # test.
    OutageAnnouncement.objects.filter(pk=announcement.pk).update(last_seen_at=when)


def test_no_announcements_means_no_matches():
    address = _address()
    assert find_matches_for_address(address) == []


def test_whole_street_location_matches_regardless_of_house_number():
    address = _address(street="Tumanyan", house_number=999)
    announcement = _announcement()
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Tumanyan", kind=LocationKind.WHOLE_STREET, street="Tumanyan",
    )
    matches = find_matches_for_address(address)
    assert len(matches) == 1
    assert matches[0].confidence == Confidence.FULL_ADDRESS


def test_street_range_matches_number_inside_range():
    address = _address(street="Adonts", house_number=5)
    announcement = _announcement()
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Adonts 2-7", kind=LocationKind.STREET_RANGE,
        street="Adonts", house_low=2, house_high=7,
    )
    assert len(find_matches_for_address(address)) == 1


def test_street_range_excludes_number_outside_range():
    address = _address(street="Adonts", house_number=20)
    announcement = _announcement()
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Adonts 2-7", kind=LocationKind.STREET_RANGE,
        street="Adonts", house_low=2, house_high=7,
    )
    assert find_matches_for_address(address) == []


def test_different_street_name_never_matches():
    address = _address(street="Adonts", house_number=5)
    announcement = _announcement()
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Bakunts 2-7", kind=LocationKind.STREET_RANGE,
        street="Bakunts", house_low=2, house_high=7,
    )
    assert find_matches_for_address(address) == []


def test_street_name_match_is_case_and_whitespace_insensitive():
    address = _address(street="  adonts  ", house_number=5)
    announcement = _announcement()
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="ADONTS 2-7", kind=LocationKind.STREET_RANGE,
        street="ADONTS", house_low=2, house_high=7,
    )
    assert len(find_matches_for_address(address)) == 1


def test_parity_even_excludes_odd_house_number():
    address = _address(street="Ulnetsu", house_number=59)
    announcement = _announcement()
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Ulnetsu 58-62 even", kind=LocationKind.STREET_RANGE,
        street="Ulnetsu", house_low=58, house_high=62, parity=Parity.EVEN,
    )
    assert find_matches_for_address(address) == []


def test_parity_odd_includes_odd_house_number():
    address = _address(street="Khorenatsi", house_number=47)
    announcement = _announcement()
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Khorenatsi 47 odd", kind=LocationKind.STREET_RANGE,
        street="Khorenatsi", house_low=47, house_high=49, parity=Parity.ODD,
    )
    assert len(find_matches_for_address(address)) == 1


def test_street_number_range_never_matches_a_house_number():
    address = _address(street="Vardashen", house_number=5)
    announcement = _announcement()
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Vardashen 1-12 streets", kind=LocationKind.STREET_NUMBER_RANGE,
        street="Vardashen", house_low=1, house_high=12,
    )
    assert find_matches_for_address(address) == []


def test_unparsed_location_never_matches():
    address = _address(street="Whatever", house_number=1)
    announcement = _announcement()
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="???", kind=LocationKind.UNPARSED, is_matchable=False,
    )
    assert find_matches_for_address(address) == []


def test_house_number_sub_boundary_blocks_a_higher_sub():
    address = _address(street="Avetisyan", house_number=80, house_number_sub="3")
    announcement = _announcement()
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Avetisyan 67-80/2", kind=LocationKind.STREET_RANGE,
        street="Avetisyan", house_low=67, house_high=80, house_high_sub="2",
    )
    assert find_matches_for_address(address) == []


def test_house_number_sub_boundary_allows_a_sub_within_bound():
    address = _address(street="Avetisyan", house_number=80, house_number_sub="1")
    announcement = _announcement()
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Avetisyan 67-80/2", kind=LocationKind.STREET_RANGE,
        street="Avetisyan", house_low=67, house_high=80, house_high_sub="2",
    )
    assert len(find_matches_for_address(address)) == 1


def test_interior_number_matches_regardless_of_sub():
    address = _address(street="Avetisyan", house_number=75, house_number_sub="9")
    announcement = _announcement()
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Avetisyan 67-80/2", kind=LocationKind.STREET_RANGE,
        street="Avetisyan", house_low=67, house_high=80, house_high_sub="2",
    )
    assert len(find_matches_for_address(address)) == 1


def test_ena_style_raw_text_match_is_low_confidence():
    address = _address(region=Region.ARARAT, street="Aygezard", house_number=999)
    announcement = _announcement(
        marz="Արարատի", raw_address_text="Aygezard village, partial",
        provider=Provider.ENA, parse_status=ParseStatus.OK,
    )
    matches = find_matches_for_address(address)
    assert len(matches) == 1
    assert matches[0].confidence == Confidence.STREET_ONLY
    assert matches[0].announcement == announcement


def test_raw_text_match_ignores_house_number_entirely():
    # This is the documented ENA precision gap: house 999 and house 1
    # both match, since raw-text matching only works at street-name
    # granularity.
    high_number = _address(region=Region.ARARAT, street="Aygezard", house_number=999, external_id="1")
    low_number = _address(region=Region.ARARAT, street="Aygezard", house_number=1, external_id="2")
    _announcement(marz="Արարատի", raw_address_text="Aygezard village, partial", provider=Provider.ENA)
    assert len(find_matches_for_address(high_number)) == 1
    assert len(find_matches_for_address(low_number)) == 1


def test_raw_text_no_match_when_street_absent():
    address = _address(region=Region.ARARAT, street="Nonexistent")
    _announcement(marz="Արարատի", raw_address_text="Aygezard village, partial", provider=Provider.ENA)
    assert find_matches_for_address(address) == []


def test_failed_parse_status_is_excluded_from_matching():
    address = _address(region=Region.ARARAT, street="Aygezard")
    _announcement(
        marz="Արարատի", raw_address_text="Aygezard everything, unreliable dump",
        provider=Provider.ENA, parse_status=ParseStatus.FAILED,
    )
    assert find_matches_for_address(address) == []


def test_unmapped_marz_never_matches_even_with_a_perfect_street_match():
    address = _address(region=Region.YEREVAN, street="Kasyan")
    _announcement(marz="Սյունիքի", raw_address_text="Kasyan street, partial", provider=Provider.ENA)
    assert find_matches_for_address(address) == []


def test_announcement_with_future_end_time_is_a_candidate():
    address = _address(street="Tumanyan", house_number=1)
    announcement = _announcement(ends_at=timezone.now() + datetime.timedelta(days=1))
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Tumanyan", kind=LocationKind.WHOLE_STREET, street="Tumanyan",
    )
    assert len(find_matches_for_address(address)) == 1


def test_announcement_ended_within_grace_period_is_still_a_candidate():
    address = _address(street="Tumanyan", house_number=1)
    announcement = _announcement(ends_at=timezone.now() - datetime.timedelta(hours=1))
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Tumanyan", kind=LocationKind.WHOLE_STREET, street="Tumanyan",
    )
    # default MATCH_END_GRACE_HOURS is 6 -- 1 hour past ends_at is still in.
    assert len(find_matches_for_address(address)) == 1


def test_announcement_ended_well_past_grace_period_is_excluded():
    address = _address(street="Tumanyan", house_number=1)
    announcement = _announcement(ends_at=timezone.now() - datetime.timedelta(days=30))
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Tumanyan", kind=LocationKind.WHOLE_STREET, street="Tumanyan",
    )
    # Would otherwise be a perfect structured match -- excluded purely
    # because it's long over, which is the whole point of the bound.
    assert find_matches_for_address(address) == []


def test_missing_end_time_falls_back_to_recent_last_seen_at():
    address = _address(street="Tumanyan", house_number=1)
    announcement = _announcement(ends_at=None)  # e.g. a "partial" ENA parse with no time match
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Tumanyan", kind=LocationKind.WHOLE_STREET, street="Tumanyan",
    )
    # last_seen_at defaults to "now" at creation -- within the default
    # 3-day staleness window, so this is still a candidate.
    assert len(find_matches_for_address(address)) == 1


def test_match_confidence_is_the_shared_enum_not_a_bare_string():
    high_address = _address(street="Tumanyan", house_number=10, external_id="1")
    high_announcement = _announcement(external_ref="ref-high")
    OutageLocation.objects.create(
        announcement=high_announcement, raw_fragment="Tumanyan", kind=LocationKind.WHOLE_STREET, street="Tumanyan",
    )
    low_address = _address(region=Region.ARARAT, street="Aygezard", external_id="2")
    _announcement(marz="Արարատի", raw_address_text="Aygezard village", provider=Provider.ENA, external_ref="ref-low")

    assert find_matches_for_address(high_address)[0].confidence is Confidence.FULL_ADDRESS
    assert find_matches_for_address(low_address)[0].confidence is Confidence.STREET_ONLY


def test_missing_end_time_and_stale_last_seen_at_is_excluded():
    address = _address(street="Tumanyan", house_number=1)
    announcement = _announcement(ends_at=None)
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Tumanyan", kind=LocationKind.WHOLE_STREET, street="Tumanyan",
    )
    _backdate_last_seen(announcement, timezone.now() - datetime.timedelta(days=30))
    assert find_matches_for_address(address) == []


def test_match_confidence_for_announcement_full_address():
    address = _address(street="Tumanyan", house_number=1)
    announcement = _announcement()
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Tumanyan", kind=LocationKind.WHOLE_STREET, street="Tumanyan",
    )
    assert match_confidence_for_announcement(address, announcement) is Confidence.FULL_ADDRESS


def test_match_confidence_for_announcement_no_match_returns_none():
    address = _address(street="Nonexistent")
    announcement = _announcement(raw_address_text="Tumanyan street")
    assert match_confidence_for_announcement(address, announcement) is None


def test_match_confidence_for_announcement_ignores_the_time_window_bound():
    # Unlike find_matches_for_address(), this is a pure text check --
    # a long-expired announcement still reports a confidence here, since
    # the time bound exists to limit the production scan, not to define
    # what "is a match" means.
    address = _address(street="Tumanyan", house_number=1)
    announcement = _announcement(ends_at=timezone.now() - datetime.timedelta(days=365))
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Tumanyan", kind=LocationKind.WHOLE_STREET, street="Tumanyan",
    )
    assert match_confidence_for_announcement(address, announcement) is Confidence.FULL_ADDRESS
    assert find_matches_for_address(address) == []


def test_ena_with_house_range_locations_is_full_address():
    address = _address(region=Region.YEREVAN, street="Շարուրի", house_number=8)
    announcement = _announcement(
        marz="Երևան", provider=Provider.ENA, raw_address_text="Շարուրի փողոց 7, 8, 9 շենքեր",
        external_ref="ena-houses",
    )
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="8", kind=LocationKind.STREET_RANGE,
        street="Շարուրի", house_low=8, house_high=8,
    )
    matches = find_matches_for_address(address)
    assert len(matches) == 1
    assert matches[0].confidence == Confidence.FULL_ADDRESS


def test_ena_locality_scoping_rejects_wrong_city():
    address = _address(
        region=Region.ARARAT, district_or_city="Արարատ քաղաք", street="Շիրակի", house_number=1,
    )
    announcement = _announcement(
        marz="Արարատի", provider=Provider.ENA, external_ref="ena-multi",
        raw_address_text="Մասիս քաղաք՝ Շիրակի փողոց",
    )
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Շիրակի", kind=LocationKind.WHOLE_STREET,
        street="Շիրակի", locality="Մասիս քաղաք",
    )
    assert find_matches_for_address(address) == []


def test_ena_locality_scoping_accepts_matching_city():
    address = _address(
        region=Region.ARARAT, district_or_city="Մասիս քաղաք", street="Շիրակի", house_number=1,
    )
    announcement = _announcement(
        marz="Արարատի", provider=Provider.ENA, external_ref="ena-multi-ok",
        raw_address_text="Մասիս քաղաք՝ Շիրակի փողոց",
    )
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Շիրակի", kind=LocationKind.WHOLE_STREET,
        street="Շիրակի", locality="Մասիս քաղաք",
    )
    assert len(find_matches_for_address(address)) == 1


def test_ena_whole_area_matches_district_or_city():
    address = _address(region=Region.ARARAT, district_or_city="Ուջան", street="unused", house_number=1)
    announcement = _announcement(
        marz="Արարատի", provider=Provider.ENA, external_ref="ena-village",
        raw_address_text="Ուջան գյուղ մասնակի",
    )
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Ուջան գյուղ", kind=LocationKind.WHOLE_AREA,
        street="Ուջան",
    )
    assert len(find_matches_for_address(address)) == 1


def test_ena_non_address_only_does_not_match():
    address = _address(region=Region.YEREVAN, street="Anything", house_number=1)
    announcement = _announcement(
        marz="Երևան", provider=Provider.ENA, external_ref="ena-biz",
        raw_address_text="«Foo» ՍՊԸ",
    )
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="«Foo» ՍՊԸ", kind=LocationKind.NON_ADDRESS,
        street=None, is_matchable=False,
    )
    # Locations exist → no STREET_ONLY fallback; non_address → no match.
    assert find_matches_for_address(address) == []

