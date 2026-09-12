from django.db import models

from common.enums import Provider
from ingestion.models import RawContent
from processing.address_grammar import LocationKind, Parity

__all__ = ["OutageType", "ParseStatus", "OutageAnnouncement", "OutageLocation"]


class OutageType(models.TextChoices):
    PLANNED = "planned", "Planned"
    EMERGENCY = "emergency", "Emergency"


class ParseStatus(models.TextChoices):
    OK = "ok", "OK"
    PARTIAL = "partial", "Partial"
    FAILED = "failed", "Failed"


class OutageAnnouncement(models.Model):
    """
    One row per distinct outage announcement, built by process_raw_content
    from a parsed ingestion.RawContent row (see processing/parsers/*).
    `external_ref` is the idempotency key that makes re-running the
    command against overlapping fetches safe -- see processing/idempotency.py.
    """

    provider = models.CharField(max_length=32, choices=Provider.choices, db_index=True)
    outage_type = models.CharField(max_length=16, choices=OutageType.choices)
    is_preliminary = models.BooleanField(default=False)

    # Kept as free text, not yet normalized to a canonical marz/city list
    # (see docs/project-plan.md §7 -- still an open item).
    marz = models.CharField(max_length=128, blank=True, null=True)
    district_or_city = models.CharField(max_length=128, blank=True, null=True)

    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    raw_heading_text = models.TextField(blank=True, default="")
    # Always populated, even for Veolia rows that also get OutageLocation
    # rows -- the full address-list text as the source wrote it.
    raw_address_text = models.TextField(blank=True, default="")

    external_ref = models.CharField(max_length=128)
    parse_status = models.CharField(max_length=16, choices=ParseStatus.choices)

    first_seen_raw_content = models.ForeignKey(RawContent, on_delete=models.PROTECT, related_name="+")
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "external_ref"], name="unique_provider_external_ref"),
        ]
        indexes = [
            models.Index(fields=["provider", "starts_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_provider_display()} {self.outage_type} @ {self.marz or '?'} ({self.parse_status})"


class OutageLocation(models.Model):
    """
    One row per decomposed address-list item. Veolia-only in v1 -- ENA
    planned announcements keep their address text verbatim on
    raw_address_text and never get OutageLocation rows (see the
    fidelity-split decision in docs/phase-1-processing-plan.md §4).
    """

    announcement = models.ForeignKey(OutageAnnouncement, on_delete=models.CASCADE, related_name="locations")

    raw_fragment = models.TextField()
    kind = models.CharField(
        max_length=32,
        choices=[(k.value, k.name.replace("_", " ").title()) for k in LocationKind],
    )
    street = models.CharField(max_length=256, blank=True, null=True)
    house_low = models.IntegerField(null=True, blank=True)
    house_low_sub = models.CharField(max_length=8, blank=True, null=True)
    house_high = models.IntegerField(null=True, blank=True)
    house_high_sub = models.CharField(max_length=8, blank=True, null=True)
    parity = models.CharField(
        max_length=8,
        choices=[(p.value, p.name.title()) for p in Parity],
        default=Parity.ANY.value,
    )
    is_matchable = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["street"]),
        ]

    def __str__(self) -> str:
        return f"{self.street or '?'} [{self.kind}] ({self.announcement_id})"
