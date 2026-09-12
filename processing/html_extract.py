"""
Extracts the specific section/posts each processing/parsers/* function
expects out of the full page HTML actually stored in RawContent.content.

Needed because ingestion deliberately stores pages verbatim with no DOM
parsing (see ingestion/fetchers/http.py's docstring) — parse_planned_section()
expects the already-isolated text of ENA's "attenbody" section, and
parse_post() expects one already-split-out Telegram post, not the whole
page either one was actually fetched from. This module is that missing
middle step, run once per RawContent row before handing text to a parser.
"""
from bs4 import BeautifulSoup


def _text_with_line_breaks(element) -> str:
    # get_text() alone doesn't turn <br> into a line break, so the
    # headline/body split parse_post() relies on (first \n) would be
    # lost — replace each <br> with an explicit text node first.
    for br in element.find_all("br"):
        br.replace_with("\n")
    return element.get_text()


def extract_ena_planned_section(html: str) -> str | None:
    """
    Text of the element whose id contains "attenbody" (the "Պլանային
    անջատումներ" section) — see ena_planned.parse_planned_section()'s
    docstring for why that's the expected input. Returns None if no
    such element is found (e.g. the page's markup changed).

    Best-effort against ENA's real markup: no live-fetched sample of
    the actual page was available while writing this (see the repo's
    README for the sandbox's network limitation), only the already-
    flattened prose in the fixtures. Confirm against a live fetch
    before relying on this for real ENA data.
    """
    soup = BeautifulSoup(html, "html.parser")
    element = soup.find(id=lambda value: value and "attenbody" in value)
    return _text_with_line_breaks(element) if element is not None else None


def extract_veolia_telegram_posts(html: str) -> list[tuple[str, str]]:
    """
    (data_post_id, post_text) pairs for every post on the fetched
    preview page, in document order. post_text keeps its line breaks
    since parse_post() splits the headline from the body on the first
    newline. Telegram's public t.me/s/<channel> preview markup is
    stable and matches ingestion's own fixture
    (ingestion/tests/fixtures/veolia_telegram_sample.html), so this one
    is trusted without the same "unverified against live" caveat as
    the ENA extractor above.
    """
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    for message in soup.select("div.tgme_widget_message[data-post]"):
        text_element = message.select_one(".tgme_widget_message_text")
        if text_element is not None:
            posts.append((message["data-post"], _text_with_line_breaks(text_element)))
    return posts
