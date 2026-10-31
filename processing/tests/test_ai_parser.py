import datetime as dt
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from common.enums import Provider
from ingestion.models import FetchStatus, RawContent
from processing.address_grammar import LocationKind, Parity
from processing.management.commands.process_raw_content import Command
from processing.models import OutageAnnouncement, OutageLocation
from processing.parsers.ai_parser import (
    AILocationItem,
    ai_location_to_parsed_locations,
    is_ai_parser_available,
    parse_building_clause,
    parse_ena_day_block_ai,
    parse_veolia_post_ai,
    _extract_retry_delay,
    _generate_with_fallback,
)
from google.genai.errors import ClientError


def test_extract_retry_delay():
    assert _extract_retry_delay(Exception("Quota exceeded. Please retry in 32s.")) == 33.0
    assert _extract_retry_delay(Exception("Unknown error"), default=5.0) == 5.0


@patch("time.sleep")
def test_generate_with_fallback_retries_on_429(mock_sleep):
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "{}"

    # First call raises 429, second call succeeds
    error_429 = ClientError(429, {"error": {"message": "Please retry in 2s.", "status": "RESOURCE_EXHAUSTED"}})
    mock_client.models.generate_content.side_effect = [error_429, mock_resp]

    from pydantic import BaseModel
    class DummySchema(BaseModel):
        pass

    with override_settings(GEMINI_REQUEST_DELAY_SECONDS=0.0):
        resp = _generate_with_fallback(mock_client, "prompt", "instruction", DummySchema)
        assert resp == mock_resp
        assert mock_sleep.called



def test_is_ai_parser_available():
    with override_settings(USE_AI_PARSER=False, GEMINI_API_KEY="test-key"):
        assert is_ai_parser_available() is False

    with override_settings(USE_AI_PARSER=True, GEMINI_API_KEY=""):
        assert is_ai_parser_available() is False

    with override_settings(USE_AI_PARSER=True, GEMINI_API_KEY="test-key"):
        assert is_ai_parser_available() is True


def test_parse_building_clause_ranges_and_singles():
    # Single building
    b1 = parse_building_clause("23")
    assert len(b1) == 1
    assert b1[0][1] == "street_range"
    assert b1[0][2] == 23 and b1[0][4] == 23

    # Range with suffix
    b2 = parse_building_clause("1-29Ա")
    assert len(b2) == 1
    assert b2[0][1] == "street_range"
    assert b2[0][2] == 1 and b2[0][4] == 29

    # Even parity range with sub
    b3 = parse_building_clause("58-58/4 զույգ շենքեր")
    assert len(b3) == 1
    assert b3[0][1] == "street_range"
    assert b3[0][2] == 58 and b3[0][4] == 58
    assert b3[0][5] == "4"
    assert b3[0][6] == "even"

    # Comma-separated list of buildings
    b4 = parse_building_clause("21/1, 23, 25")
    assert len(b4) == 3
    assert b4[0][2] == 21 and b4[0][3] == "1"
    assert b4[1][2] == 23
    assert b4[2][2] == 25


def test_ai_location_to_parsed_locations_whole_street():
    loc = AILocationItem(
        street_name="Կոմիտասի պողոտա",
        building_numbers="",
        is_whole_street=True,
    )
    res = ai_location_to_parsed_locations(loc)
    assert len(res) == 1
    assert res[0].kind == LocationKind.WHOLE_STREET
    assert res[0].street == "Կոմիտասի պողոտա"


def test_ai_location_to_parsed_locations_range():
    loc = AILocationItem(
        street_name="Գյուլբենկյան փողոց",
        building_numbers="1-29",
        house_low=1,
        house_high=29,
        parity="any",
    )
    res = ai_location_to_parsed_locations(loc)
    assert len(res) == 1
    assert res[0].kind == LocationKind.STREET_RANGE
    assert res[0].house_low == 1
    assert res[0].house_high == 29


@patch("processing.parsers.ai_parser.get_genai_client")
def test_parse_veolia_post_ai_success(mock_get_client):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """{
        "outage_type": "emergency",
        "marz": "Երևան",
        "district_or_city": "Արաբկիր",
        "starts_at_iso": "2026-09-02T17:30:00",
        "ends_at_iso": "2026-09-02T20:00:00",
        "raw_heading_text": "Վթարային ջրանջատում Երևանի Արաբկիր վարչական շրջանում",
        "raw_address_text": "Վ.Համբարձումյանի, Գյուլբենկյանի 1-29Ա Շենքերի",
        "locations": [
            {
                "street_name": "Վ.Համբարձումյան",
                "building_numbers": "",
                "is_whole_street": true
            },
            {
                "street_name": "Գյուլբենկյան",
                "building_numbers": "1-29Ա",
                "is_whole_street": false,
                "house_low": 1,
                "house_high": 29
            }
        ]
    }"""
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    result = parse_veolia_post_ai("sample text", year=2026)
    assert result.outage_type == "emergency"
    assert result.marz == "Երևան"
    assert result.district_or_city == "Արաբկիր"
    assert result.starts_at == dt.datetime(2026, 9, 2, 17, 30)
    assert result.ends_at == dt.datetime(2026, 9, 2, 20, 0)
    assert len(result.locations) == 2
    assert result.locations[0].kind == LocationKind.WHOLE_STREET
    assert result.locations[1].kind == LocationKind.STREET_RANGE


@patch("processing.parsers.ai_parser.get_genai_client")
def test_parse_ena_day_block_ai_success(mock_get_client):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """{
        "date_iso": "2026-09-04",
        "is_preliminary": false,
        "slots": [
            {
                "marz_or_yerevan": "Երևան",
                "district": "Կենտրոն",
                "city_or_village": null,
                "starts_at_iso": "2026-09-04T10:00:00",
                "ends_at_iso": "2026-09-04T13:00:00",
                "raw_heading_text": "Երևանի Կենտրոն վարչական շրջան",
                "raw_address_text": "Տոլստոյի փողոց 8–64 առանձնատներ",
                "locations": [
                    {
                        "street_name": "Տոլստոյի փողոց",
                        "building_numbers": "8-64",
                        "is_whole_street": false,
                        "house_low": 8,
                        "house_high": 64
                    }
                ]
            }
        ]
    }"""
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    results = parse_ena_day_block_ai("sample text", is_preliminary=False, year=2026)
    assert len(results) == 1
    slot = results[0]
    assert slot.marz_or_yerevan == "Երևան"
    assert slot.district == "Կենտրոն"
    assert slot.starts_at == dt.datetime(2026, 9, 4, 10, 0)
    assert slot.ends_at == dt.datetime(2026, 9, 4, 13, 0)
    assert len(slot.parsed_locations) == 1
    assert slot.parsed_locations[0].house_low == 8
    assert slot.parsed_locations[0].house_high == 64


@pytest.mark.django_db
@patch("processing.management.commands.process_raw_content.is_ai_parser_available")
@patch("processing.management.commands.process_raw_content.parse_veolia_post_ai")
def test_process_veolia_uses_ai_parser_when_available(mock_parse_ai, mock_is_available):
    from processing.parsers.veolia_telegram import VeoliaAnnouncement
    from processing.address_grammar import ParsedLocation, LocationKind

    mock_is_available.return_value = True
    mock_parse_ai.return_value = VeoliaAnnouncement(
        outage_type="emergency",
        marz="Երևան",
        district_or_city="Արաբկիր",
        starts_at=dt.datetime(2026, 9, 2, 17, 30),
        ends_at=dt.datetime(2026, 9, 2, 20, 0),
        raw_heading_text="AI Parsed Heading",
        raw_address_text="AI Parsed Address",
        locations=[
            ParsedLocation(raw_fragment="Արաբկիր 1", kind=LocationKind.WHOLE_STREET, street="Արաբկիր 1")
        ],
        parse_status="ok",
    )

    raw = RawContent.objects.create(
        provider=Provider.VEOLIA_TELEGRAM,
        fetch_status=FetchStatus.OK,
        reference="t.me/s/VeoliaJur",
        content="""<div class="tgme_widget_message" data-post="VeoliaJur/99999">
            <div class="tgme_widget_message_text">Custom text</div>
        </div>""",
    )

    cmd = Command()
    summary = {"rows": 0, "announcements_created": 0, "locations_created": 0, "extraction_failed": 0, "row_errors": 0, "announcements_touched": 0}
    cmd._process_veolia(raw, summary)

    assert mock_parse_ai.called
    assert OutageAnnouncement.objects.filter(external_ref="VeoliaJur/99999").exists()
    ann = OutageAnnouncement.objects.get(external_ref="VeoliaJur/99999")
    assert ann.raw_heading_text == "AI Parsed Heading"
    assert ann.locations.count() == 1


@pytest.mark.django_db
@patch("processing.management.commands.process_raw_content.is_ai_parser_available")
@patch("processing.management.commands.process_raw_content.parse_veolia_post_ai")
def test_process_veolia_falls_back_to_regex_on_ai_error(mock_parse_ai, mock_is_available):
    mock_is_available.return_value = True
    mock_parse_ai.side_effect = RuntimeError("API quota exceeded")

    post_content = """Վթարային ջրանջատում Երևանի Արաբկիր վարչական շրջանում սեպտեմբերի 2-ին\n
«Վեոլիա Ջուր» ընկերությունը տեղեկացնում է, որ վթարային աշխատանքներով պայմանավորված ս.թ սեպտեմբերի 2-ին ժամը 17:30-20:00-ն կդադարեցվի Կոմիտասի ջրամատակարարումը:"""

    raw = RawContent.objects.create(
        provider=Provider.VEOLIA_TELEGRAM,
        fetch_status=FetchStatus.OK,
        reference="t.me/s/VeoliaJur",
        content=f"""<div class="tgme_widget_message" data-post="VeoliaJur/88888">
            <div class="tgme_widget_message_text">{post_content}</div>
        </div>""",
    )

    cmd = Command()
    summary = {"rows": 0, "announcements_created": 0, "locations_created": 0, "extraction_failed": 0, "row_errors": 0, "announcements_touched": 0}
    cmd._process_veolia(raw, summary)

    assert mock_parse_ai.called
    assert OutageAnnouncement.objects.filter(external_ref="VeoliaJur/88888").exists()
    ann = OutageAnnouncement.objects.get(external_ref="VeoliaJur/88888")
    assert ann.parse_status == "ok"
    assert ann.locations.filter(street__icontains="Կոմիտաս").exists()

