"""
Manual test tool: check whether one specific Address matches one
specific OutageAnnouncement, and preview (or actually send) the
resulting notification -- without needing a real, currently-live
announcement or waiting on the scheduler.

Deliberately bypasses matching.matcher._relevant_announcements()'s
time-window bound, since a hand-picked test announcement (or an old
one) would otherwise be silently excluded for being "too old" -- that
filter exists to bound the production scan, not to define what "is a
match" means, so skipping it here is testing tooling, not a behavior
change.
"""
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Address
from matching.geography import canonicalize_marz
from matching.matcher import match_confidence_for_announcement
from notifications.models import NotificationLog
from notifications.send import format_message, send_notification
from processing.models import OutageAnnouncement


class Command(BaseCommand):
    help = (
        "Check whether --address matches --announcement, bypassing the usual "
        "time-window filter, and preview the notification text. Pass --send "
        "to actually log and deliver it via Telegram."
    )

    def add_arguments(self, parser):
        parser.add_argument("--address", type=int, required=True, help="Address id")
        parser.add_argument("--announcement", type=int, required=True, help="OutageAnnouncement id")
        parser.add_argument("--send", action="store_true", help="Log and deliver a real notification if it matches")

    def handle(self, *args, **options):
        try:
            address = Address.objects.select_related("user").get(id=options["address"])
        except Address.DoesNotExist:
            raise CommandError(f"No Address with id={options['address']}")
        try:
            announcement = OutageAnnouncement.objects.get(id=options["announcement"])
        except OutageAnnouncement.DoesNotExist:
            raise CommandError(f"No OutageAnnouncement with id={options['announcement']}")

        region = canonicalize_marz(announcement.marz)
        geography_ok = region is not None and region == address.region
        confidence = match_confidence_for_announcement(address, announcement)
        matched = geography_ok and confidence is not None

        self.stdout.write(f"Address: {address} ({address.get_region_display()})")
        self.stdout.write(f"Announcement: {announcement}")
        self.stdout.write(
            f"Geography: announcement marz '{announcement.marz}' -> {region}; "
            f"{'OK' if geography_ok else 'MISMATCH'} against address region '{address.region}'"
        )
        self.stdout.write(f"Text/location match: {confidence.label if confidence else 'no match'}")
        self.stdout.write(f"Would match: {matched}")

        if not matched:
            return

        preview = NotificationLog(user=address.user, address=address, outage_announcement=announcement, match_confidence=confidence)
        self.stdout.write("\n--- Notification preview ---")
        self.stdout.write(format_message(preview))

        if options["send"]:
            log, _ = NotificationLog.objects.get_or_create(
                user=address.user, address=address, outage_announcement=announcement,
                defaults={"channel": address.user.channel, "match_confidence": confidence},
            )
            success = send_notification(log)
            self.stdout.write(f"\nSent: {success}")
