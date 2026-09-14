"""
Turns matching.matcher.Match results into logged NotificationLog rows.
Deliberately does not send anything -- see
docs/phase-1.3-users-matching-notifications-plan.md for why "compute +
log" and "actually deliver" (the not-yet-built bot) are kept as separate
steps: this keeps the matching+dedup logic fully testable without a live
bot token or network access.
"""
from accounts.models import Address
from matching.matcher import find_matches_for_address
from notifications.models import NotificationLog


def compute_pending_notifications() -> int:
    """
    For every Address, find outage announcements it matches that don't
    already have a NotificationLog row, and log one with status=PENDING.
    Safe to re-run: get_or_create against the (address, outage_announcement)
    uniqueness constraint makes an already-logged match a no-op. Returns
    the number of newly created rows.
    """
    created = 0
    for address in Address.objects.select_related("user").all():
        for match in find_matches_for_address(address):
            _, was_created = NotificationLog.objects.get_or_create(
                address=match.address,
                outage_announcement=match.announcement,
                defaults={
                    "user": match.address.user,
                    "channel": match.address.user.channel,
                    "match_confidence": match.confidence,
                },
            )
            if was_created:
                created += 1
    return created
