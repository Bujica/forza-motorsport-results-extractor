from __future__ import annotations

import re
import unicodedata


def has_suspicious_name_symbol(value: str) -> bool:
    return bool(re.search(r"[^\w\s.\-']", value or "", flags=re.UNICODE))


def has_numeric_name_prefix(value: str) -> bool:
    return bool(re.match(r"^\s*\d{1,3}[\s_\-.]+.+", value or ""))


def driver_name_review_trigger(value: str) -> str | None:
    if not str(value or "").strip():
        return "driver_name_empty"
    if has_numeric_name_prefix(value):
        return "numeric_prefix"
    if has_suspicious_name_symbol(value):
        return "invalid_symbol"
    return None


def ambiguous_raw_track(track: str) -> str:
    match = re.search(r"ambiguous layout\)?\s*:\s*(.+)$", track or "", flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def track_key(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(text))
    clean = "".join(char for char in nfkd if not unicodedata.combining(char)).lower()
    return re.sub(r"[^a-z0-9]+", " ", clean).strip()


def track_suggestions(track: str, known_tracks: list[str]) -> list[str]:
    raw = ambiguous_raw_track(track)
    if not raw:
        return []
    raw_key = track_key(raw)
    if not raw_key:
        return []
    return [
        candidate for candidate in known_tracks
        if track_key(candidate).startswith(raw_key)
    ][:8]
