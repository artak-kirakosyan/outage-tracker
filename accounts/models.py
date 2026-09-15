from django.db import models

from common.enums import Channel, Region

__all__ = ["User", "Address", "format_house_number"]


def format_house_number(number: int, sub: str) -> str:
    """
    A numeric sub (e.g. "12") is a separate '/'-style sub-address
    ("21/12", matching ENA/Veolia's own "21/12" notation -- see
    processing/address_grammar.py); a non-numeric sub (e.g. "A"/"Ա")
    is a direct suffix ("4A"). Without this distinction both forms
    concatenate identically and "21" sub "12" silently renders as the
    unreadable "2112".
    """
    if not sub:
        return str(number)
    if sub.isdigit():
        return f"{number}/{sub}"
    return f"{number}{sub}"


class User(models.Model):
    """
    One row per person interacting with the bot. Identity is
    (channel, external_id) rather than a dedicated telegram_id field --
    only 'telegram' exists today (see the not-yet-built bot/ app), but
    keeping identity as (channel, external_id) means a future channel is
    a new Channel value and a new row shape, not a rename or a migration
    that touches every table with a FK to User.
    """

    channel = models.CharField(max_length=32, choices=Channel.choices, default=Channel.TELEGRAM)
    external_id = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["channel", "external_id"], name="unique_channel_external_id"),
        ]

    def __str__(self) -> str:
        return f"{self.channel}:{self.external_id}"


class Address(models.Model):
    """
    A location a User wants outage matching for. Matches against every
    provider by default -- no provider field here. If a future paywall
    needs to scope an address to specific providers, that's an additive
    field then, not a redesign now (same reserved-but-unused shape as
    common.enums.Provider.GAZPROM already uses elsewhere).

    district_or_city and street are deliberately plain CharFields, not a
    choices/FK field: no place-name list exists yet, matching runs on
    exact user input for now, and this keeps introducing an
    admin-managed list later a data migration rather than a schema
    change. `region` is the one exception with real choices today
    because common.enums.Region is currently a small, closed set (see
    docs/phase-1.3-users-matching-notifications-plan.md).

    house_number/house_number_sub mirror processing.models.OutageLocation's
    house_low/house_low_sub shape on purpose -- the matching layer will be
    comparing an Address's house number against an OutageLocation's
    range, and keeping the same (int main, optional string sub) shape on
    both sides avoids a conversion step at match time.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")

    region = models.CharField(max_length=32, choices=Region.choices)
    district_or_city = models.CharField(max_length=255)
    street = models.CharField(max_length=255)
    house_number = models.PositiveIntegerField()
    house_number_sub = models.CharField(max_length=16, blank=True, default="")

    label = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        base = f"{self.street} {format_house_number(self.house_number, self.house_number_sub)}"
        return f"{self.label} ({base})" if self.label else base
