import logging

from django.conf import settings

from ingestion.fetchers.base import BaseFetcher, FetchTarget
from ingestion.models import Provider, SourceType

logger = logging.getLogger(__name__)

# Separator that cannot appear in post text (post IDs are "channel/12345")
_POST_SEPARATOR = "\n\n---POST---\n\n"
_ID_TEXT_SEP = "\t"


def serialize_posts(posts: list[tuple[str, str]]) -> str:
    """
    Serialise (post_id, text) pairs into a stable, canonical string that
    contains no Telegram-session volatile data (no data-view tokens, no
    view counts, no HTML). Used both by the fetcher (to store dedup-safe
    content) and by process_raw_content (to re-extract posts without HTML
    parsing). Format: pairs joined by _POST_SEPARATOR, each as
    "post_id<TAB>text".
    """
    return _POST_SEPARATOR.join(
        f"{post_id}{_ID_TEXT_SEP}{text}" for post_id, text in posts
    )


def deserialize_posts(content: str) -> list[tuple[str, str]]:
    """Inverse of serialize_posts — returns (post_id, text) pairs."""
    posts = []
    for chunk in content.split(_POST_SEPARATOR):
        chunk = chunk.strip()
        if not chunk:
            continue
        sep_idx = chunk.find(_ID_TEXT_SEP)
        if sep_idx == -1:
            continue
        posts.append((chunk[:sep_idx], chunk[sep_idx + 1:]))
    return posts


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

    Note: Telegram's preview page embeds a session-scoped data-view token
    on every message element that changes with each request even when the
    post content is identical. Storing the full HTML would defeat
    get_latest_content()'s deduplication. fetch_one() therefore extracts
    the post (id, text) pairs and serialises them into a stable canonical
    string (no HTML, no volatile tokens) via serialize_posts() so that
    byte-identical post content produces byte-identical stored content.
    """

    provider = Provider.VEOLIA_TELEGRAM
    source_type = SourceType.TELEGRAM_TEXT

    def fetch_targets(self) -> list[FetchTarget]:
        channel = settings.VEOLIA_TELEGRAM_CHANNEL
        return [FetchTarget(reference=f"https://t.me/s/{channel}")]

    def fetch_one(self, target: FetchTarget) -> str:
        from ingestion.fetchers.http import fetch_page_text
        from processing.html_extract import extract_veolia_telegram_posts

        html = fetch_page_text(target.reference)
        posts = extract_veolia_telegram_posts(html)
        if not posts:
            logger.warning(
                "VeoliaTelegramFetcher: no posts extracted from %s — "
                "storing full HTML so the failure is visible in the admin.",
                target.reference,
            )
            return html
        return serialize_posts(posts)
