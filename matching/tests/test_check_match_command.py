from io import StringIO
from unittest import mock
from uuid import uuid4

import pytest
from django.core.management import CommandError, call_command

from accounts.models import Address, User
from common.enums import Region
from ingestion.models import FetchStatus, Provider, RawContent, SourceType
from notifications.models import NotificationLog, NotificationStatus
from processing.address_grammar import LocationKind
from processing.models import OutageAnnouncement, OutageLocation, OutageType, ParseStatus

pytestmark = pytest.mark.django_db


def _address(**kwargs):
    user = User.objects.create(external_id=kwargs.pop("external_id", "1"))
    defaults = dict(region=Region.YEREVAN, district_or_city="Kentron", street="Tumanyan", house_number=10)
    defaults.update(kwargs)
    return Address.objects.create(user=user, **defaults)


def _announcement(marz="Երևան", provider=Provider.VEOLIA_TELEGRAM, external_ref=None):
    raw = RawContent.objects.create(
        provider=provider, source_type=SourceType.TELEGRAM_TEXT,
        reference="https://t.me/s/VeoliaJur", fetch_status=FetchStatus.OK, content="x",
    )
    return OutageAnnouncement.objects.create(
        provider=provider, outage_type=OutageType.EMERGENCY, marz=marz,
        external_ref=external_ref or f"ref-{uuid4()}", parse_status=ParseStatus.OK, first_seen_raw_content=raw,
    )


def _run(**options):
    out = StringIO()
    call_command("check_match", stdout=out, **options)
    return out.getvalue()


def test_reports_no_match_for_wrong_geography():
    address = _address(region=Region.ARARAT)
    announcement = _announcement(marz="Երևան")
    output = _run(address=address.id, announcement=announcement.id)
    assert "MISMATCH" in output
    assert "Would match: False" in output


def test_reports_match_and_previews_message_for_a_real_match():
    address = _address(street="Tumanyan", house_number=1)
    announcement = _announcement()
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Tumanyan", kind=LocationKind.WHOLE_STREET, street="Tumanyan",
    )
    output = _run(address=address.id, announcement=announcement.id)
    assert "Would match: True" in output
    assert "Notification preview" in output
    assert "Source: Veolia" in output
    assert NotificationLog.objects.count() == 0  # preview only, --send not passed


def test_unknown_address_id_raises_command_error():
    announcement = _announcement()
    with pytest.raises(CommandError):
        _run(address=999999, announcement=announcement.id)


def test_unknown_announcement_id_raises_command_error():
    address = _address()
    with pytest.raises(CommandError):
        _run(address=address.id, announcement=999999)


@mock.patch("notifications.send.Bot")
def test_send_flag_logs_and_delivers_without_touching_other_pending_rows(mock_bot_cls):
    mock_bot = mock_bot_cls.return_value
    mock_bot.__aenter__ = mock.AsyncMock(return_value=mock_bot)
    mock_bot.__aexit__ = mock.AsyncMock(return_value=False)
    mock_bot.send_message = mock.AsyncMock()

    address = _address(street="Tumanyan", house_number=1)
    announcement = _announcement()
    OutageLocation.objects.create(
        announcement=announcement, raw_fragment="Tumanyan", kind=LocationKind.WHOLE_STREET, street="Tumanyan",
    )

    # An unrelated PENDING row that --send must not touch.
    other_address = _address(external_id="2", street="Other", house_number=1)
    other_announcement = _announcement()
    NotificationLog.objects.create(
        user=other_address.user, address=other_address, outage_announcement=other_announcement,
        match_confidence="full_address",
    )

    output = _run(address=address.id, announcement=announcement.id, send=True)

    assert "Sent: True" in output
    log = NotificationLog.objects.get(address=address)
    assert log.status == NotificationStatus.SENT
    assert mock_bot.send_message.call_count == 1

    other_log = NotificationLog.objects.get(address=other_address)
    assert other_log.status == NotificationStatus.PENDING
