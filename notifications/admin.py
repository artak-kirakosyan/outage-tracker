from django.contrib import admin

from notifications.models import NotificationLog


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = (
        "id", "user", "address", "outage_announcement", "channel",
        "match_confidence", "status", "created_at", "sent_at",
    )
    list_filter = ("channel", "match_confidence", "status")
    autocomplete_fields = ("user", "address")
    readonly_fields = ("created_at",)
