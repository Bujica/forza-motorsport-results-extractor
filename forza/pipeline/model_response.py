from __future__ import annotations

import json
import re

from ..exceptions import ParseError
from ..domain.lap import parse_lap_time_ms, strip_dirty_symbol



def clean_json_content(text: str) -> str:
    """Strip markdown fences and leading/trailing whitespace from model JSON."""

    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()



def parse_and_validate_response(content: str) -> dict:
    """Parse and validate the short-key extraction JSON returned by the model."""

    cleaned = clean_json_content(content)
    result = json.loads(cleaned)
    if not isinstance(result, dict):
        raise ParseError("Response is not a JSON object")
    validate_extracted_response(result)
    return result



def validate_extracted_response(data: dict) -> None:
    """Validate the model's short-key extraction response.

    Expected shape:
      - ``t``: track name
      - ``e``: list of entries
      - each entry has ``dr``, ``ca``, ``cl``, and ``bl``
    """

    if "t" not in data:
        raise ParseError("Missing field 't' (track name)")
    if "e" not in data or not isinstance(data["e"], list):
        raise ParseError("Missing or invalid field 'e' (entries list)")
    for i, entry in enumerate(data["e"]):
        for field in ("dr", "ca", "cl", "bl"):
            if field not in entry:
                raise ParseError(f"Entry {i} missing field '{field}'")
        bl = entry["bl"]
        if bl is not None:
            bl_str = strip_dirty_symbol(str(bl))
            if parse_lap_time_ms(bl_str) is None:
                raise ParseError(f"Entry {i} has unparseable lap time: '{bl}'")

