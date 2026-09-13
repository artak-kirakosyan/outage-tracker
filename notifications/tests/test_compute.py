import pytest

from accounts.models import Address, User
from common.enums import Region
from ingestion.models import FetchStatus, Provider, RawContent, SourceType
from notifications.compute import compute_pending_notifications
from notifications.models import NotificationLog, NotificationStatus
from processing.address_grammar import LocationKind
from processing.models import OutageAnnouncement, OutageLocation, OutageType, ParseStatus

pytestmark = pytest.mark.django_db


def _announcement_with_location(street: str):
    raw = RawContent.objects.create(
        provider=Provider.VEOLIA_TELEGRAM, source_type=SourceType.TELEGRAM_TEXT,
        reference="https://t.me/s/VeoliaJur", fetch_status=FetchStatus.OK, content="x",
    )
    announcement = OutageAnnouncement.objects.create(
        provider=Provider.VEOLIA_TELEGRAM, outage_type=OutageType.EMERGENCY, marz="Երևան",
        external_ref="ref-1", parse_status=ParseStatus.OK, first_seen_raw_content=raw,
    )
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment=street, kind=LocationKind.WHOLE_STREET, street=street,
    )
    return announcement


def _matching_setup():
    user = User.objects.create(external_id="1")
    address = Address.objects.create(
        user=user, region=Region.YEREVAN, district_or_city="Kentron", street="Tumanyan", house_number=1,
    )
    announcement = _announcement_with_location("Tumanyan")
    return user, address, announcement


def test_creates_a_pending_notification_for_a_real_match():
    user, address, announcement = _matching_setup()
    created = compute_pending_notifications()
    assert created == 1
    log = NotificationLog.objects.get()
    assert log.user == user
    assert log.address == address
    assert log.outage_announcement == announcement
    assert log.match_confidence == "high"
    assert log.status == NotificationStatus.PENDING


def test_no_notification_when_nothing_matches():
    user = User.objects.create(external_id="1")
    Address.objects.create(
        user=user, region=Region.YEREVAN, district_or_city="Kentron",
        street="Nonexistent", house_number=1,
    )
    _announcement_with_location("Tumanyan")
    assert compute_pending_notifications() == 0
    assert NotificationLog.objects.count() == 0


def test_rerunning_is_idempotent():
    _matching_setup()
    first = compute_pending_notifications()
    second = compute_pending_notifications()
    assert first == 1
    assert second == 0
    assert NotificationLog.objects.count() == 1


def test_two_addresses_matching_the_same_announcement_both_get_logged():
    announcement = _announcement_with_location("Tumanyan")
    user_a = User.objects.create(external_id="1")
    user_b = User.objects.create(external_id="2")
    Address.objects.create(
        user=user_a, region=Region.YEREVAN, district_or_city="Kentron", street="Tumanyan", house_number=1,
    )
    Address.objects.create(
        user=user_b, region=Region.YEREVAN, district_or_city="Kentron", street="Tumanyan", house_number=2,
    )
    created = compute_pending_notifications()
    assert created == 2
    assert set(NotificationLog.objects.values_list("outage_announcement", flat=True)) == {announcement.id}
