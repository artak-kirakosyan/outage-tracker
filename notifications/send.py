"""
Delivers PENDING NotificationLog rows via the Telegram Bot API. Kept
separate from notifications/compute.py (matching + logging) and from
bot/ (user-facing conversation) so delivery is testable without a live
bot token.

Only PENDING rows are retried automatically on each run -- a FAILED
send is left for manual investigation rather than retried forever
against a possibly-permanently-bad chat id.
"""
import asyncio
import logging

from django.conf import settings
from django.utils import timezone
from telegram import Bot
from telegram.error import TelegramError

from common.enums import Confidence
from notifications.models import NotificationLog, NotificationStatus

logger = logging.getLogger(__name__)

# Shown only for STREET_ONLY matches (currently: every ENA planned
# match -- see matching/matcher.py). That path matches on street name
# alone with no house-number check, so it over-matches by design (see
# docs/phase-1.3-users-matching-notifications-plan.md); the recipient
# needs that caveat up front, not buried after a long raw address list.
_STREET_ONLY_CAVEAT = (
    "This is a street-level match only (no house-number check) -- "
    "the outage below may not reach your exact address."
)


def _format_message(log: NotificationLog) -> str:
    """
    Our own match details (source, confidence, area, caveat) come
    first and are kept short; the source's own announcement text --
    which for an ENA match can be a long, undecomposed block covering
    many streets -- is appended last under its own heading so the two
    are never run together.
    """
    announcement = log.outage_announcement
    lines = [
        f"Outage notice for {log.address}",
        "",
        f"Source: {announcement.get_provider_display()} ({announcement.get_outage_type_display()})",
        f"Confidence: {log.get_match_confidence_display()}",
    ]
    area = ", ".join(p for p in (announcement.marz, announcement.district_or_city) if p)
    if area:
        lines.append(f"Area: {area}")
    if announcement.starts_at and announcement.ends_at:
        lines.append(f"Time: {announcement.starts_at:%Y-%m-%d %H:%M} - {announcement.ends_at:%H:%M}")
    if log.match_confidence == Confidence.STREET_ONLY:
        lines += ["", _STREET_ONLY_CAVEAT]
    lines += ["", "Announcement text:", announcement.raw_address_text]
    return "\n".join(lines)


async def _send_one(bot: Bot, log: NotificationLog) -> tuple[NotificationLog, bool]:
    try:
        await bot.send_message(chat_id=int(log.user.external_id), text=_format_message(log))
        return log, True
    except TelegramError:
        logger.exception("Failed to send NotificationLog id=%s", log.id)
        return log, False


async def _send_all(logs: list[NotificationLog]) -> list[tuple[NotificationLog, bool]]:
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    async with bot:
        return [await _send_one(bot, log) for log in logs]


def send_pending_notifications() -> dict:
    """
    Sync entry point (wraps the async Bot API) so it's callable from
    the scheduler thread / a management command. All DB writes happen
    synchronously after the async send batch, not inside it -- Django's
    ORM is sync-only and raises if called from a running event loop.
    """
    logs = list(
        NotificationLog.objects.filter(status=NotificationStatus.PENDING)
        .select_related("user", "address", "outage_announcement")
    )
    if not logs:
        return {"sent": 0, "failed": 0}

    results = asyncio.run(_send_all(logs))

    summary = {"sent": 0, "failed": 0}
    now = timezone.now()
    for log, success in results:
        if success:
            log.status = NotificationStatus.SENT
            log.sent_at = now
            log.save(update_fields=["status", "sent_at"])
            summary["sent"] += 1
        else:
            log.status = NotificationStatus.FAILED
            log.save(update_fields=["status"])
            summary["failed"] += 1
    return summary
