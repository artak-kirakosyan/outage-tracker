from unittest import mock

import pytest
from telegram.error import TelegramError

from accounts.models import Address, User
from common.enums import Confidence, Region
from ingestion.models import FetchStatus, Provider, RawContent, SourceType
from notifications.models import NotificationLog, NotificationStatus
from notifications.send import send_pending_notifications
from processing.models import OutageAnnouncement, OutageType, ParseStatus

pytestmark = pytest.mark.django_db


def _pending_log(external_id="123", match_confidence=Confidence.FULL_ADDRESS, provider=Provider.VEOLIA_TELEGRAM):
    user = User.objects.create(external_id=external_id)
    address = Address.objects.create(
        user=user, region=Region.YEREVAN, district_or_city="Kentron", street="Tumanyan", house_number=1,
    )
    raw = RawContent.objects.create(
        provider=provider, source_type=SourceType.TELEGRAM_TEXT,
        reference="https://t.me/s/VeoliaJur", fetch_status=FetchStatus.OK, content="x",
    )
    announcement = OutageAnnouncement.objects.create(
        provider=provider, outage_type=OutageType.EMERGENCY, marz="Երևան",
        raw_address_text="Tumanyan", external_ref=f"ref-{external_id}", parse_status=ParseStatus.OK,
        first_seen_raw_content=raw,
    )
    return NotificationLog.objects.create(
        user=user, address=address, outage_announcement=announcement, match_confidence=match_confidence,
    )


def _mock_bot(mock_bot_cls, send_side_effect=None):
    mock_bot = mock_bot_cls.return_value
    mock_bot.__aenter__ = mock.AsyncMock(return_value=mock_bot)
    mock_bot.__aexit__ = mock.AsyncMock(return_value=False)
    mock_bot.send_message = mock.AsyncMock(side_effect=send_side_effect)
    return mock_bot


@mock.patch("notifications.send.Bot")
def test_sends_pending_notifications_and_marks_sent(mock_bot_cls):
    mock_bot = _mock_bot(mock_bot_cls)
    log = _pending_log()

    summary = send_pending_notifications()

    assert summary == {"sent": 1, "failed": 0}
    log.refresh_from_db()
    assert log.status == NotificationStatus.SENT
    assert log.sent_at is not None
    mock_bot.send_message.assert_called_once()


@mock.patch("notifications.send.Bot")
def test_failed_send_marks_failed_and_is_not_retried_next_run(mock_bot_cls):
    _mock_bot(mock_bot_cls, send_side_effect=TelegramError("boom"))
    log = _pending_log()

    summary = send_pending_notifications()
    assert summary == {"sent": 0, "failed": 1}
    log.refresh_from_db()
    assert log.status == NotificationStatus.FAILED

    second_summary = send_pending_notifications()
    assert second_summary == {"sent": 0, "failed": 0}


def test_no_pending_notifications_is_a_no_op():
    assert send_pending_notifications() == {"sent": 0, "failed": 0}


@mock.patch("notifications.send.Bot")
def test_message_surfaces_provider_and_confidence(mock_bot_cls):
    mock_bot = _mock_bot(mock_bot_cls)
    _pending_log(match_confidence=Confidence.FULL_ADDRESS, provider=Provider.VEOLIA_TELEGRAM)

    send_pending_notifications()

    text = mock_bot.send_message.call_args.kwargs["text"]
    assert "Veolia" in text
    assert "Street and house number matched" in text  # Confidence.FULL_ADDRESS display


@mock.patch("notifications.send.Bot")
def test_street_only_match_includes_caveat_and_ena_match_does_not(mock_bot_cls):
    mock_bot = _mock_bot(mock_bot_cls)
    _pending_log(external_id="1", match_confidence=Confidence.STREET_ONLY, provider=Provider.ENA)
    _pending_log(external_id="2", match_confidence=Confidence.FULL_ADDRESS, provider=Provider.VEOLIA_TELEGRAM)

    send_pending_notifications()

    texts = [call.kwargs["text"] for call in mock_bot.send_message.call_args_list]
    assert sum("street-level match only" in t for t in texts) == 1


@mock.patch("notifications.send.Bot")
def test_own_details_and_raw_announcement_text_are_clearly_separated(mock_bot_cls):
    mock_bot = _mock_bot(mock_bot_cls)
    _pending_log()

    send_pending_notifications()

    text = mock_bot.send_message.call_args.kwargs["text"]
    notification = "Outage notice for Tumanyan 1\n\
                    Source: Veolia — Telegram channel (Emergency)\n\
                    Confidence: Street and house number matched\n\
                    Area: Երևան\n\
                    \n\
                    Announcement text:\n\
                    Tumanyan\n\
    "
    notification_lines = notification.split("\n")
    for notification_line in notification_lines:
        print(f"line is {notification_line}")
        assert notification_line.strip() in text
