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
