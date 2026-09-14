from django.core.management.base import BaseCommand

from notifications.compute import compute_pending_notifications


class Command(BaseCommand):
    help = "Match every Address against outage announcements and log any new matches as pending notifications."

    def handle(self, *args, **options):
        created = compute_pending_notifications()
        self.stdout.write(f"Logged {created} new pending notification(s).")
