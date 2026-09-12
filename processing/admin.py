from django.contrib import admin

from processing.models import OutageAnnouncement, OutageLocation


class OutageLocationInline(admin.TabularInline):
    model = OutageLocation
    extra = 0
    readonly_fields = (
        "raw_fragment", "kind", "street", "house_low", "house_low_sub",
        "house_high", "house_high_sub", "parity", "is_matchable",
    )
    can_delete = False


@admin.register(OutageAnnouncement)
class OutageAnnouncementAdmin(admin.ModelAdmin):
    list_display = (
        "id", "provider", "outage_type", "marz", "district_or_city",
        "starts_at", "ends_at", "parse_status", "last_seen_at",
    )
    list_filter = ("provider", "outage_type", "parse_status", "is_preliminary")
    search_fields = ("marz", "district_or_city", "raw_heading_text", "raw_address_text", "external_ref")
    readonly_fields = [f.name for f in OutageAnnouncement._meta.fields]
    date_hierarchy = "starts_at"
    inlines = [OutageLocationInline]
