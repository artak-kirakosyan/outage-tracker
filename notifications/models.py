from django.db import models

from common.enums import Channel

__all__ = ["NotificationStatus", "NotificationLog"]


class NotificationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"


class NotificationLog(models.Model):
    """
    One row per (address, outage announcement) match worth notifying
    about. Created by notifications.compute.compute_pending_notifications
    with status=PENDING -- actually delivering it (via the not-yet-built
    bot) is a separate step that updates status/sent_at later, kept
    apart so match-finding stays testable without a live bot token or
    network access (see docs/phase-1.3-users-matching-notifications-plan.md).

    The (address, outage_announcement) uniqueness IS the idempotency
    guarantee: re-running compute_pending_notifications against an
    announcement that's already logged here -- including one only
    reconfirmed via OutageAnnouncement.last_seen_at -- is a no-op,
    mirroring the external_ref dedup OutageAnnouncement itself already
    uses against RawContent.
    """

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="notifications")
    address = models.ForeignKey("accounts.Address", on_delete=models.CASCADE, related_name="notifications")
    outage_announcement = models.ForeignKey(
        "processing.OutageAnnouncement", on_delete=models.CASCADE, related_name="notifications"
    )

    channel = models.CharField(max_length=32, choices=Channel.choices, default=Channel.TELEGRAM)
    # Copied from matching.matcher.Match.confidence at creation time --
    # kept as plain text rather than importing matching's dataclass here,
    # since this is what the eventual notification copy reads to decide
    # whether to show the "this covers part of your street" caveat (see
    # the plan doc's note on ENA's precision gap).
    match_confidence = models.CharField(max_length=16, blank=True, default="")

    status = models.CharField(max_length=16, choices=NotificationStatus.choices, default=NotificationStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["address", "outage_announcement"], name="unique_address_announcement_notification"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.address} -> announcement {self.outage_announcement_id} ({self.status})"
