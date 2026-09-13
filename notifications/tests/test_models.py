import pytest
from django.db import IntegrityError

from accounts.models import Address, User
from common.enums import Channel, Region
from ingestion.models import FetchStatus, Provider, RawContent, SourceType
from notifications.models import NotificationLog, NotificationStatus
from processing.models import OutageAnnouncement, OutageType, ParseStatus

pytestmark = pytest.mark.django_db


def _setup():
    user = User.objects.create(external_id="1")
    address = Address.objects.create(
        user=user, region=Region.YEREVAN, district_or_city="Kentron", street="Tumanyan", house_number=1,
    )
    raw = RawContent.objects.create(
        provider=Provider.VEOLIA_TELEGRAM, source_type=SourceType.TELEGRAM_TEXT,
        reference="https://t.me/s/VeoliaJur", fetch_status=FetchStatus.OK, content="x",
    )
    announcement = OutageAnnouncement.objects.create(
        provider=Provider.VEOLIA_TELEGRAM, outage_type=OutageType.EMERGENCY, marz="Երևան",
        external_ref="ref-1", parse_status=ParseStatus.OK, first_seen_raw_content=raw,
    )
    return user, address, announcement


def test_defaults_to_pending_status_and_telegram_channel():
    user, address, announcement = _setup()
    log = NotificationLog.objects.create(user=user, address=address, outage_announcement=announcement)
    assert log.status == NotificationStatus.PENDING
    assert log.channel == Channel.TELEGRAM


def test_str_includes_status():
    user, address, announcement = _setup()
    log = NotificationLog.objects.create(user=user, address=address, outage_announcement=announcement)
    assert "pending" in str(log)


def test_address_and_announcement_pair_must_be_unique():
    user, address, announcement = _setup()
    NotificationLog.objects.create(user=user, address=address, outage_announcement=announcement)
    with pytest.raises(IntegrityError):
        NotificationLog.objects.create(user=user, address=address, outage_announcement=announcement)
