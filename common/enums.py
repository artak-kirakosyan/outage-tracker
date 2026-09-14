from django.db import models


class Provider(models.TextChoices):
    """
    One entry per data *source*, not per utility — Veolia's website and
    its Telegram channel are two distinct providers even though they're
    the same utility, since they aren't assumed to publish identical
    outages.

    GAZPROM is reserved so Phase 2 slots in with zero schema change.
    Do not implement a Gazprom fetcher yet.
    """

    ENA = "ena", "ENA (Electric Network Armenia)"
    VEOLIA_WEB = "veolia_web", "Veolia — website"
    VEOLIA_TELEGRAM = "veolia_telegram", "Veolia — Telegram channel"
    GAZPROM = "gazprom", "Gazprom Armenia (reserved, not implemented)"


class Region(models.TextChoices):
    """
    Top-level geography an Address can be registered in. Named Region
    rather than Marz because Yerevan is a city with marz-equivalent
    administrative status, not itself a marz, and this needs to hold
    both without misnaming one of them.

    Deliberately small for now (see docs/phase-1.3-users-matching-notifications-plan.md)
    -- two values, expand as coverage grows. `OutageAnnouncement.marz`
    (processing/models.py) is intentionally NOT restricted to this enum:
    it's parsed verbatim from source text and needs to store whatever
    marz appears there even before that marz has address-matching
    support. This enum only constrains what a user can register an
    Address in, and the matching layer's canonicalization step.
    """

    YEREVAN = "yerevan", "Yerevan"
    ARARAT = "ararat", "Ararat"


class Confidence(models.TextChoices):
    """
    How a matching.matcher.Match was derived. Shared here, not defined
    in matching/, since notifications.NotificationLog.match_confidence
    stores the same value without importing matching's dataclass.
    """

    FULL_ADDRESS = "full_address", "Street and house number matched"
    STREET_ONLY = "street_only", "Street name only, no house number check"


class Channel(models.TextChoices):
    """
    A delivery/identity channel a User is reachable on. Only Telegram is
    implemented so far (see accounts.User) -- kept here, not inlined
    into accounts/models.py, since the not-yet-built notifications app
    will need the same enum for NotificationLog.channel rather than
    importing it from accounts.
    """

    TELEGRAM = "telegram", "Telegram"
