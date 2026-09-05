from pathlib import Path

import pytest
from django.conf import settings

from ingestion.models import FetchStatus, Provider, RawContent, SourceType
from ingestion.storage import save_raw_content

pytestmark = pytest.mark.django_db


def test_save_raw_content_ok_writes_db_row_and_file():
    raw = save_raw_content(
        provider=Provider.ENA,
        source_type=SourceType.HTML,
        reference="https://www.ena.am/Info.aspx?id=5&lang=1",
        content="<html>hello</html>",
        fetch_status=FetchStatus.OK,
    )

    assert RawContent.objects.count() == 1
    assert raw.content == "<html>hello</html>"
    assert raw.fetch_status == FetchStatus.OK
    assert raw.dump_file_path  # a relative path was recorded

    dumped_file = Path(settings.RAW_DUMP_DIRECTORY) / raw.dump_file_path
    assert dumped_file.exists()
    assert dumped_file.read_text(encoding="utf-8") == "<html>hello</html>"


def test_save_raw_content_error_writes_db_row_without_file():
    raw = save_raw_content(
        provider=Provider.VEOLIA_WEB,
        source_type=SourceType.HTML,
        reference="https://interactive.vjur.am/?ajax=list-post&page=1",
        fetch_status=FetchStatus.ERROR,
        error_message="Non-200 status: 503",
    )

    assert raw.content == ""
    assert raw.dump_file_path == ""
    assert raw.error_message == "Non-200 status: 503"


def test_raw_content_str_includes_provider_and_status():
    raw = save_raw_content(
        provider=Provider.VEOLIA_TELEGRAM,
        source_type=SourceType.TELEGRAM_TEXT,
        reference="https://t.me/s/VeoliaJur",
        content="some post text",
        fetch_status=FetchStatus.OK,
    )
    text = str(raw)
    assert "Veolia" in text
    assert "ok" in text
