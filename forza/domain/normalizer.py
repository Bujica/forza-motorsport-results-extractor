from __future__ import annotations

import re
import unicodedata
import difflib
import logging
from pathlib import Path
from dataclasses import dataclass

from .text_utils import load_nonempty_lines


log = logging.getLogger("forza")


# ── Reference data container ──────────────────────────────────────────────────

@dataclass
class ReferenceData:
    tracks:  list[str]
    cars:    list[str]
    car_map: dict[str, str]   # normalised key → original name


def load_reference_seed_text_data(tracks_file: Path, cars_file: Path) -> ReferenceData:
    """Load explicit seed/test reference text files into a ReferenceData value."""
    tracks = load_nonempty_lines(tracks_file, warn_missing=True, logger=log)
    cars = load_nonempty_lines(cars_file, warn_missing=True, logger=log)
    return ReferenceData(tracks=tracks, cars=cars, car_map=_build_car_map(cars))


def _build_car_map(cars: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for car in cars:
        key = _normalise(car, spaces=False)
        if key not in result:
            result[key] = car
    return result


# ── Normalisation helpers ─────────────────────────────────────────────────────

def _normalise(text: str, spaces: bool = True) -> str:
    nfkd = unicodedata.normalize("NFKD", str(text))
    s = "".join(c for c in nfkd if not unicodedata.combining(c))
    if not spaces:
        s = re.sub(r"\W+", "", s)
    return s.lower().strip()


def _track_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _normalise(text)).strip()


# ── Track correction ──────────────────────────────────────────────────────────

def fix_track_name(raw: str, refs: ReferenceData) -> str | None:
    """
    Match a raw OCR track name against the supplied reference tracks.

    Strategy (first match wins):
      1. Exact match (case-insensitive)
      2. Accent-normalised exact match
      3. Punctuation-insensitive exact match
      4. Unique prefix match — only when exactly one track starts with the
         prefix.  When multiple tracks share the same prefix (e.g. Le Mans
         Full Circuit vs Old Mulsanne Circuit both start with the same base
         name), returns None so the caller can flag for
         review instead of guessing the wrong layout.
      5. Fuzzy match (cutoff 0.75) — only when prefix match found zero
         candidates, to avoid masking ambiguous prefixes.
      6. Return original string unchanged (unrecognised, not ambiguous).

    Returns None when the result is ambiguous and choosing silently would risk
    returning the wrong layout. Empty raw input still returns the original empty
    string, so callers can distinguish missing text from ambiguous text.
    """
    if not raw or not refs.tracks:
        return raw

    term     = " ".join(raw.split()).strip()
    term_low = term.lower()

    # 1) Exact
    for track in refs.tracks:
        if track.lower() == term_low:
            return track

    # 2) Accent-normalised exact
    term_norm = _normalise(term)
    for track in refs.tracks:
        if _normalise(track) == term_norm:
            return track

    # 3) Punctuation-insensitive exact
    term_key = _track_key(term)
    for track in refs.tracks:
        if _track_key(track) == term_key:
            return track

    # 4) Prefix match — safe only when unambiguous
    prefix_matches = [t for t in refs.tracks if _track_key(t).startswith(term_key)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) > 1:
        # Multiple layouts share this prefix — do NOT guess.
        log.debug(
            f"[normalizer] Ambiguous prefix '{term}' matches "
            f"{[t for t in prefix_matches]} — flagging for review"
        )
        return None

    # 5) Fuzzy — only when prefix found nothing (avoids masking ambiguous cases)
    matches = difflib.get_close_matches(term, refs.tracks, n=1, cutoff=0.75)
    if matches:
        return matches[0]

    # 6) Unrecognised — return unchanged so caller can decide
    return term


# ── Car correction ────────────────────────────────────────────────────────────

def fix_car_name(raw: str, refs: ReferenceData) -> str:
    """
    Match a raw OCR car name against the pre-computed car map.

    Strategy (first match wins):
      1. Normalised exact match  (O(1))
      2. Substring match
      3. Fuzzy match  (cutoff 0.85)
      4. Return original string unchanged
    """
    if not raw or not refs.car_map:
        return raw

    raw_str  = str(raw).strip()
    raw_norm = _normalise(raw_str, spaces=False)

    # 1) Exact
    if raw_norm in refs.car_map:
        corrected = refs.car_map[raw_norm]
        if corrected != raw_str:
            log.debug(f"[car] '{raw_str}' → '{corrected}'")
        return corrected

    # 2) Substring
    candidates = [v for k, v in refs.car_map.items() if raw_norm in k]
    if len(candidates) == 1:
        log.debug(f"[car] '{raw_str}' → '{candidates[0]}' (substring)")
        return candidates[0]

    # 3) Fuzzy
    matches = difflib.get_close_matches(
        raw_str, list(refs.car_map.values()), n=1, cutoff=0.85
    )
    if matches:
        log.debug(f"[car] '{raw_str}' → '{matches[0]}' (fuzzy)")
        return matches[0]

    log.debug(f"[car] no match for '{raw_str}' — keeping original")
    return raw_str
