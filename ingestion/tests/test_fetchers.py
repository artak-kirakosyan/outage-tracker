from pathlib import Path

import pytest
import responses

from ingestion.fetchers.ena import ENAFetcher
from ingestion.fetchers.runner import run_fetcher
from ingestion.fetchers.veolia_telegram import VeoliaTelegramFetcher
from ingestion.fetchers.veolia_web import VeoliaWebFetcher
from ingestion.models import FetchStatus, RawContent

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures"


@responses.activate
def test_ena_fetcher_happy_path():
    responses.add(
        responses.GET,
        ENAFetcher.URL,
        body="<html>ena outage page</html>",
        status=200,
    )

    summary = run_fetcher(ENAFetcher())

    assert summary == {"provider": "ena", "targets": 1, "ok": 1, "unchanged": 0, "error": 0}
    row = RawContent.objects.get()
    assert row.provider == "ena"
    assert row.fetch_status == FetchStatus.OK
    assert "ena outage page" in row.content


@responses.activate
def test_veolia_web_fetcher_tolerates_partial_failure():
    fetcher = VeoliaWebFetcher()
    urls = [f"{fetcher.BASE_URL}&page={p}" for p in fetcher.PAGES]

    responses.add(responses.GET, urls[0], body="<html>page 1</html>", status=200)
    responses.add(responses.GET, urls[1], status=503)  # simulate a flaky page
    responses.add(responses.GET, urls[2], body="<html>page 3</html>", status=200)

    summary = run_fetcher(fetcher)

    # One page failing must not lose the other two rows.
    assert summary == {"provider": "veolia_web", "targets": 3, "ok": 2, "unchanged": 0, "error": 1}
    assert RawContent.objects.filter(fetch_status=FetchStatus.OK).count() == 2
    assert RawContent.objects.filter(fetch_status=FetchStatus.ERROR).count() == 1

    failed_row = RawContent.objects.get(fetch_status=FetchStatus.ERROR)
    assert "503" in failed_row.error_message


@responses.activate
def test_veolia_telegram_fetcher_stores_channel_preview():
    sample = (FIXTURES / "veolia_telegram_sample.html").read_text(encoding="utf-8")
    responses.add(
        responses.GET,
        "https://t.me/s/VeoliaJur",
        body=sample,
        status=200,
    )

    summary = run_fetcher(VeoliaTelegramFetcher())

    assert summary == {"provider": "veolia_telegram", "targets": 1, "ok": 1, "unchanged": 0, "error": 0}
    row = RawContent.objects.get()
    assert row.source_type == "telegram_text"
    assert "Կապան" in row.content  # confirms Armenian text round-trips intact


@responses.activate
def test_all_targets_failing_records_every_error_and_raises_nothing():
    fetcher = VeoliaWebFetcher()
    for page in fetcher.PAGES:
        responses.add(responses.GET, f"{fetcher.BASE_URL}&page={page}", status=500)

    summary = run_fetcher(fetcher)  # must not raise

    assert summary["ok"] == 0
    assert summary["error"] == 3
    assert RawContent.objects.count() == 3


@responses.activate
def test_unchanged_content_is_skipped_but_changed_content_is_saved():
    responses.add(responses.GET, ENAFetcher.URL, body="<html>version A</html>", status=200)
    run_fetcher(ENAFetcher())
    assert RawContent.objects.count() == 1

    # Second run, identical content — must NOT create a duplicate row.
    responses.reset()
    responses.add(responses.GET, ENAFetcher.URL, body="<html>version A</html>", status=200)
    summary = run_fetcher(ENAFetcher())
    assert summary == {"provider": "ena", "targets": 1, "ok": 0, "unchanged": 1, "error": 0}
    assert RawContent.objects.count() == 1

    # Third run, content actually changed — must create a new row.
    responses.reset()
    responses.add(responses.GET, ENAFetcher.URL, body="<html>version B</html>", status=200)
    summary = run_fetcher(ENAFetcher())
    assert summary == {"provider": "ena", "targets": 1, "ok": 1, "unchanged": 0, "error": 0}
    assert RawContent.objects.count() == 2
