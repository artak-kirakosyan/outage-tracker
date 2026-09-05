from django.db import models


class Provider(models.TextChoices):
    """
    One entry per data *source*, not per utility — Veolia's website and
    its Telegram channel are two distinct providers even though they're
    the same utility, since we don't yet know if they publish the same
    outages (see plan doc: "no deduping at the raw layer").

    GAZPROM is reserved now so Phase 2 slots in with zero schema change,
    per the plan's provider-abstraction decision. Do not implement a
    Gazprom fetcher yet.
    """

    ENA = "ena", "ENA (Electric Network Armenia)"
    VEOLIA_WEB = "veolia_web", "Veolia — website"
    VEOLIA_TELEGRAM = "veolia_telegram", "Veolia — Telegram channel"
    GAZPROM = "gazprom", "Gazprom Armenia (reserved, not implemented)"


class SourceType(models.TextChoices):
    HTML = "html", "HTML page"
    TELEGRAM_TEXT = "telegram_text", "Telegram channel preview page"


class FetchStatus(models.TextChoices):
    OK = "ok", "OK"
    ERROR = "error", "Error"


class RawContent(models.Model):
    """
    One row per fetch attempt, successful or not. This is the entire
    Phase 0.5 schema — no parsing into structured outages happens here.

    `processed` exists now but is unused until Phase 1's raw->structured
    parser is built; it's here so Phase 1 doesn't need a migration just
    to start marking rows as consumed.
    """

    provider = models.CharField(max_length=32, choices=Provider.choices, db_index=True)
    source_type = models.CharField(max_length=32, choices=SourceType.choices)

    # The URL fetched (website providers) or the t.me/s/<handle> URL
    # (Veolia Telegram) — kept as a plain string rather than a URLField
    # so we're not blocked by Django's stricter validation on edge cases.
    reference = models.CharField(max_length=1024)

    # Raw response body, verbatim. This is the source of truth; the file
    # dump on disk (see storage.py) is a redundant, disposable copy for
    # convenient manual eyeballing only.
    content = models.TextField(blank=True, default="")

    fetched_at = models.DateTimeField(auto_now_add=True, db_index=True)

    fetch_status = models.CharField(max_length=16, choices=FetchStatus.choices)
    error_message = models.TextField(blank=True, default="")

    # Path to the mirrored on-disk copy, if the dump succeeded. Kept
    # relative to RAW_DUMP_DIRECTORY so the DB isn't tied to one machine's
    # absolute paths.
    dump_file_path = models.CharField(max_length=1024, blank=True, default="")

    processed = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Reserved for Phase 1's raw→structured parser. Not used in Phase 0.5.",
    )

    class Meta:
        ordering = ["-fetched_at"]
        indexes = [
            models.Index(fields=["provider", "fetched_at"]),
            models.Index(fields=["provider", "processed"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.get_provider_display()} [{self.source_type}] "
            f"@ {self.fetched_at:%Y-%m-%d %H:%M} ({self.fetch_status})"
        )
