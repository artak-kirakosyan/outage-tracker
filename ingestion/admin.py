from django.contrib import admin

from ingestion.models import RawContent


@admin.register(RawContent)
class RawContentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "provider",
        "source_type",
        "fetch_status",
        "fetched_at",
        "processed",
        "content_preview",
    )
    list_filter = ("provider", "source_type", "fetch_status", "processed")
    search_fields = ("reference", "content", "error_message")
    readonly_fields = (
        "provider",
        "source_type",
        "reference",
        "content",
        "fetched_at",
        "fetch_status",
        "error_message",
        "dump_file_path",
    )
    date_hierarchy = "fetched_at"

    @admin.display(description="Content preview")
    def content_preview(self, obj: RawContent) -> str:
        text = (obj.content or "").strip().replace("\n", " ")
        return (text[:120] + "…") if len(text) > 120 else text
