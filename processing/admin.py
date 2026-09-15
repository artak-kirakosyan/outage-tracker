from django.contrib import admin
from django.db.models import Count

from processing.models import OutageAnnouncement, OutageLocation, ParseStatus


class OutageLocationInline(admin.TabularInline):
    model = OutageLocation
    extra = 0
    readonly_fields = (
        "raw_fragment", "kind", "street", "house_low", "house_low_sub",
        "house_high", "house_high_sub", "parity", "is_matchable",
        "locality", "qualifier",
    )
    can_delete = False


class BadlyParsedFilter(admin.SimpleListFilter):
    title = "parse health"
    parameter_name = "parse_health"

    def lookups(self, request, model_admin):
        return (("bad", "Partial or failed"),)

    def queryset(self, request, queryset):
        if self.value() == "bad":
            return queryset.filter(parse_status__in=[ParseStatus.PARTIAL, ParseStatus.FAILED])
        return queryset


class NoLocationsFilter(admin.SimpleListFilter):
    title = "locations"
    parameter_name = "locations"

    def lookups(self, request, model_admin):
        return (("none", "No locations"),)

    def queryset(self, request, queryset):
        if self.value() == "none":
            return queryset.annotate(_loc_count=Count("locations")).filter(_loc_count=0)
        return queryset


@admin.register(OutageAnnouncement)
class OutageAnnouncementAdmin(admin.ModelAdmin):
    list_display = (
        "id", "provider", "outage_type", "marz", "district_or_city",
        "starts_at", "ends_at", "parse_status", "last_seen_at",
    )
    list_filter = (
        "provider", "outage_type", "parse_status", "is_preliminary",
        BadlyParsedFilter, NoLocationsFilter,
    )
    search_fields = ("marz", "district_or_city", "raw_heading_text", "raw_address_text", "external_ref")
    readonly_fields = [f.name for f in OutageAnnouncement._meta.fields]
    date_hierarchy = "starts_at"
    inlines = [OutageLocationInline]
