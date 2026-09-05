import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class FetchError(RuntimeError):
    """Raised when a page/resource could not be fetched successfully."""


def fetch_page_text(url: str) -> str:
    """
    GET a URL and return its raw response body as text.

    Deliberately dumb: no HTML parsing here (the old repo's `parse_url`
    returned a BeautifulSoup object; we don't need a DOM yet). Phase 0.5
    only needs the raw bytes stored — DOM parsing belongs in Phase 1's
    processor, which will read this same text back out of
    RawContent.content.
    """
    headers = {"User-Agent": settings.HTTP_FETCH_USER_AGENT}
    try:
        response = requests.get(
            url, headers=headers, timeout=settings.HTTP_FETCH_TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        raise FetchError(f"Request failed for '{url}': {exc}") from exc

    if response.status_code != 200:
        raise FetchError(f"Non-200 status for '{url}': {response.status_code}")

    return response.text
