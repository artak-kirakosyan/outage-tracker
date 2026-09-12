from pathlib import Path

from processing.html_extract import extract_ena_planned_section, extract_veolia_telegram_posts
from processing.normalize import normalize_multiline

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_veolia_telegram_posts_returns_each_post_with_its_id():
    html = (FIXTURES / "veolia_telegram_page_sample.html").read_text(encoding="utf-8")

    posts = extract_veolia_telegram_posts(html)

    assert [post_id for post_id, _ in posts] == [
        "VeoliaJur/14500",
        "VeoliaJur/14503",
        "VeoliaJur/14519",
    ]


def test_extract_veolia_telegram_posts_preserves_line_breaks_for_headline_split():
    html = (FIXTURES / "veolia_telegram_page_sample.html").read_text(encoding="utf-8")

    posts = dict(extract_veolia_telegram_posts(html))
    text = posts["VeoliaJur/14500"]

    # parse_post() splits the headline from the body on the first
    # newline -- if <br> didn't survive as \n, this would collapse into
    # one line and headline parsing would silently break.
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    assert lines[0].startswith("Վթարային ջրանջատում Արմավիրի մարզի")
    assert "16:40" in text


def test_extract_veolia_telegram_posts_round_trips_through_parse_post():
    """
    The real end-to-end path: extract from a page, then feed straight
    into the existing parser, same as process_raw_content will.
    """
    from processing.parsers.veolia_telegram import parse_post

    html = (FIXTURES / "veolia_telegram_page_sample.html").read_text(encoding="utf-8")
    posts = extract_veolia_telegram_posts(html)

    for post_id, text in posts:
        result = parse_post(text, year=2026)
        assert result.parse_status in ("ok", "partial"), f"{post_id} failed to parse: {result}"
        assert result.starts_at is not None


def test_extract_ena_planned_section_finds_attenbody_element():
    html = (FIXTURES / "ena_page_sample.html").read_text(encoding="utf-8")

    section = extract_ena_planned_section(html)

    assert section is not None
    assert "Կենտրոն վարչական շրջան" in section
    assert "Եր. Քոչարի փողոց" in section


def test_extract_ena_planned_section_round_trips_through_parser():
    from processing.parsers.ena_planned import parse_planned_section

    html = (FIXTURES / "ena_page_sample.html").read_text(encoding="utf-8")
    section = extract_ena_planned_section(html)
    text = normalize_multiline(section)

    results = parse_planned_section(text, year=2026)

    assert results
    assert all(r.parse_status != "failed" for r in results)


def test_extract_ena_planned_section_returns_none_when_element_missing():
    assert extract_ena_planned_section("<html><body>nothing here</body></html>") is None


def test_extract_veolia_telegram_posts_returns_empty_list_when_none_found():
    assert extract_veolia_telegram_posts("<html><body>nothing here</body></html>") == []
