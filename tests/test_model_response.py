from __future__ import annotations

import json

import pytest

from forza.exceptions import ParseError
from forza.pipeline.model_response import (
    clean_json_content,
    parse_and_validate_response,
    validate_extracted_response,
)


VALID_RESPONSE = {
    "t": "Hakone Club Circuit",
    "e": [
        {
            "dr": "Driver",
            "ca": "Mazda MX-5 Miata",
            "cl": "PI 700 A",
            "bl": "01:23.456",
        }
    ],
}



def test_clean_json_content_strips_markdown_fences_and_whitespace() -> None:
    assert clean_json_content("  ```json\n{\"t\": \"Track\"}\n```  ") == '{"t": "Track"}'
    assert clean_json_content("```\n{}\n```") == "{}"
    assert clean_json_content("  {\"t\": \"Track\"}  ") == '{"t": "Track"}'



def test_parse_and_validate_response_accepts_valid_short_key_json() -> None:
    content = f"```json\n{json.dumps(VALID_RESPONSE)}\n```"

    assert parse_and_validate_response(content) == VALID_RESPONSE



def test_parse_and_validate_response_rejects_non_object_json() -> None:
    with pytest.raises(ParseError, match="Response is not a JSON object"):
        parse_and_validate_response("[]")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"e": []}, "Missing field 't'"),
        ({"t": "Track"}, "Missing or invalid field 'e'"),
        ({"t": "Track", "e": {}}, "Missing or invalid field 'e'"),
        ({"t": "Track", "e": [{"ca": "Car", "cl": "A", "bl": "01:23.456"}]}, "missing field 'dr'"),
        ({"t": "Track", "e": [{"dr": "Driver", "cl": "A", "bl": "01:23.456"}]}, "missing field 'ca'"),
        ({"t": "Track", "e": [{"dr": "Driver", "ca": "Car", "bl": "01:23.456"}]}, "missing field 'cl'"),
        ({"t": "Track", "e": [{"dr": "Driver", "ca": "Car", "cl": "A"}]}, "missing field 'bl'"),
        ({"t": "Track", "e": [{"dr": "Driver", "ca": "Car", "cl": "A", "bl": "not a lap"}]}, "unparseable lap time"),
    ],
)
def test_validate_extracted_response_rejects_invalid_payloads(payload: dict, message: str) -> None:
    with pytest.raises(ParseError, match=message):
        validate_extracted_response(payload)



def test_validate_extracted_response_allows_null_lap_time_and_dirty_markers() -> None:
    validate_extracted_response(
        {
            "t": "Track",
            "e": [
                {"dr": "Driver 1", "ca": "Car 1", "cl": "A", "bl": None},
                {"dr": "Driver 2", "ca": "Car 2", "cl": "A", "bl": "01:23.456▲"},
                {"dr": "Driver 3", "ca": "Car 3", "cl": "A", "bl": "01:23.456⚠"},
                {"dr": "Driver 4", "ca": "Car 4", "cl": "A", "bl": "01:23.456⚠️"},
                {"dr": "Driver 5", "ca": "Car 5", "cl": "A", "bl": "01:23.456!"},
                {"dr": "Driver 6", "ca": "Car 6", "cl": "A", "bl": "01:23.456△"},
            ],
        }
    )

