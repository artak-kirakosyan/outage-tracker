from django.conf import settings

from ingestion.fetchers.base import BaseFetcher, FetchTarget
from ingestion.models import Provider, SourceType


class VeoliaTelegramFetcher(BaseFetcher):
    """
    Scrapes Telegram's public, unauthenticated preview page
    (t.me/s/<channel>) instead of using the Bot API (which needs the bot
    to be an *admin* of the channel — not possible, it's Veolia's
    channel) or a userbot/MTProto session (persistent authenticated
    session under a real phone number — account-flag risk, overkill for
    a public channel). See plan doc for the full reasoning.

    Confirmed handle: VeoliaJur (https://t.me/s/VeoliaJur), public,
    ~27.9K subscribers, actively posting.

    Only returns recent posts (Telegram doesn't paginate this preview
    back indefinitely) — that's a known, accepted limitation, not a bug:
    full channel history isn't part of the product.
    """

    provider = Provider.VEOLIA_TELEGRAM
    source_type = SourceType.TELEGRAM_TEXT

    def fetch_targets(self) -> list[FetchTarget]:
        channel = settings.VEOLIA_TELEGRAM_CHANNEL
        return [FetchTarget(reference=f"https://t.me/s/{channel}")]
