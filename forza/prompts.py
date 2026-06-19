from __future__ import annotations

import hashlib
import json


DEFAULT_PROMPT_ID = "user_header_shaped_v1"


SYSTEM_PROMPTS: dict[str, str] = {
    "user_header_shaped_v1": """Return ONLY a minified JSON in a single line, without markdown.
Schema: {"t":string,"tf":int,"w":"dry"|"rain"|"unknown","e":[{"dr":string,"ca":string,"cl":string,"bl":string}]}
Fields:
    t: Track name from the visible header area. Read the track name line and also inspect the small subtitle/layout line directly under it. If a layout subtitle is visible, append it to the track family in the same string. Do not stop at the family name for tracks with visible layouts such as Sports Car Circuit, Club Circuit, Full Circuit, Short Circuit, Grand Prix Circuit, or Road Course. Ignore the logo and never use the image filename.
    tf: Track Temperature (°F)
    w: Check the icon next to "Weather". If it shows rain drops, w="rain". Otherwise, w="dry". Use "unknown" if not visible
    e: List of drivers:
        dr: Driver/gamertag text only. Do NOT include position numbers, level numbers, PI/class values, badges/icons/symbols/emojis.
        ca: Car
        cl: Class (PI Number+Letter). If the class letter is in a small separate box, include it, e.g. "PI 400 D".
        bl: Best lap ("MM:SS.mmm" | null). Read only the BEST LAP cell. If that cell shows a time, return that time. If another column such as TOTAL says DNF, still return the BEST LAP time. Return null only when the BEST LAP cell itself is empty, --, ---, DNF, or DNQ.
Rules:
    1. The warning-shaped dirty-lap icon is the ONLY dirty indicator. It must be immediately beside that driver's best lap time in the same best-lap cell. Do not use row color, text color, penalties, position, car/class columns, or icons elsewhere as dirty evidence.
    2. If the BEST LAP cell has a warning icon beside its time, append ▲ (e.g., "07:23.097▲"), including rows where TOTAL is DNF. Otherwise, return only the time (e.g., "00:34.149")
    3. Include all drivers, even if DNF
""",
}


def get_system_prompt(prompt_id: str = DEFAULT_PROMPT_ID) -> str:
    try:
        return SYSTEM_PROMPTS[prompt_id]
    except KeyError as exc:
        available = ", ".join(sorted(SYSTEM_PROMPTS))
        raise ValueError(f"Unknown prompt_id '{prompt_id}'. Available: {available}") from exc


def prompt_snapshot_payload(prompt_id: str = DEFAULT_PROMPT_ID) -> dict[str, str | None]:
    return {
        "system_text": get_system_prompt(prompt_id),
        "user_text_template": None,
        "response_schema_json": None,
    }


def prompt_payload_hash(
    *,
    system_text: str,
    user_text_template: str | None,
    response_schema_json: str | None,
) -> str:
    payload = {
        "system_text": system_text,
        "user_text_template": user_text_template,
        "response_schema_json": response_schema_json,
    }
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def prompt_content_hash(prompt_id: str = DEFAULT_PROMPT_ID) -> str:
    payload = prompt_snapshot_payload(prompt_id)
    return prompt_payload_hash(**payload)


def prompt_snapshot_id(prompt_id: str = DEFAULT_PROMPT_ID) -> str:
    return f"{prompt_id}:{prompt_content_hash(prompt_id)}"
