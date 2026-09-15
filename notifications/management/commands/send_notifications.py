from django.core.management.base import BaseCommand

from notifications.send import send_pending_notifications


class Command(BaseCommand):
    help = "Send every PENDING NotificationLog via Telegram."

    def handle(self, *args, **options):
        summary = send_pending_notifications()
        self.stdout.write(f"send_notifications summary: {summary}")
