from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

# ── TCR car livery names ──────────────────────────────────────────────────────
# Any race where ≥ 30 % of the grid drives one of these cars is classified TCR.
TCR_CARS: frozenset[str] = frozenset({
    "MG #20 MG6",
    "VW #22 Golf GTI",
    "#66 Astra",
    "#98 Veloster",
    "SUBARU #1 Levorg",
    "Lynk #100 03",
    "Audi #1 RS 3 LMS",
    "Peugeot #7 308",
    "#98 Elantra",
    "Honda #73 Civic",
    "Ford #17Focus ST",
    "MB #33 A45",
})

# ── Dirty lap symbol pattern ──────────────────────────────────────────────────
DIRTY_LAP_PATTERN: str = r"[▲⚠!△]+"


# ── Lap time ──────────────────────────────────────────────────────────────────

def strip_dirty_symbol(value: str) -> str:
    """
    Remove trailing dirty-lap symbol(s) and any preceding whitespace.
    Returns a clean time string (e.g. '1:23.456').
    Does NOT remove symbols from the middle or beginning.

    Unicode variation selectors (U+FE00–U+FE0F) are stripped first so that
    the emoji form ⚠️ (U+26A0 + U+FE0F) is handled identically to the plain
    text form ⚠ (U+26A0 alone).  Without this step, U+FE0F would survive the
    character-class regex and cause parse_lap_time_ms() to reject the lap time.
    """
    s = re.sub(r"[\uFE00-\uFE0F]", "", str(value).strip())
    return re.sub(rf"\s*{DIRTY_LAP_PATTERN}\s*$", "", s)


def parse_lap_time_ms(value: str | None) -> int | None:
    """Convert a lap time string to canonical integer milliseconds.

    Accepted absolute forms:
      - ``MM:SS.mmm``
      - ``SS.mmm``

    Invalid values, gap times, placeholders and nulls return ``None``.
    """
    if not value:
        return None

    raw = str(value).strip()
    if raw.lower() in {"", "--", "---", "dnf", "dnq", "null", "none"}:
        return None
    if "+" in raw:
        return None  # gap time, not an absolute lap time

    clean = strip_dirty_symbol(raw)

    # MM:SS.mmm
    m = re.match(r"^(\d+):(\d{2})(?:\.(\d{1,3}))?$", clean)
    if m:
        ms = (m.group(3) or "0")[:3].ljust(3, "0")
        return (int(m.group(1)) * 60 + int(m.group(2))) * 1000 + int(ms)

    # SS.mmm  (no minutes component)
    m2 = re.match(r"^(\d{1,2})(?:\.(\d{1,3}))?$", clean)
    if m2:
        ms = (m2.group(2) or "0")[:3].ljust(3, "0")
        return int(m2.group(1)) * 1000 + int(ms)

    return None


def format_lap_time_ms(value: int, *, dirty: bool = False) -> str:
    """Format canonical integer milliseconds as ``M:SS.mmm``."""
    if value <= 0:
        raise ValueError("lap time milliseconds must be positive")
    total_seconds, ms = divmod(int(value), 1000)
    minutes, seconds = divmod(total_seconds, 60)
    suffix = " ▲" if dirty else ""
    return f"{minutes}:{seconds:02d}.{ms:03d}{suffix}"


def parse_lap_time(value: str | None) -> float | None:
    """Compatibility wrapper returning seconds for export/UI-only derived use.

    Domain, persistence, ordering and frontier logic must use
    :func:`parse_lap_time_ms` and integer ``best_lap_ms``.
    """
    ms = parse_lap_time_ms(value)
    return None if ms is None else ms / 1000.0


def is_dirty_lap(value: str | None) -> bool:
    """Return True when the lap-time string ends with a dirty-lap symbol,
    optionally preceded by whitespace (e.g. "1:23.456 ▲")."""
    s = re.sub(r"[\uFE00-\uFE0F]", "", str(value or "").strip())
    return bool(re.search(rf"\s*{DIRTY_LAP_PATTERN}\s*$", s))


# ── Driver names ──────────────────────────────────────────────────────────────

def sanitize_driver_name(value: str | None) -> str:
    """
    Remove visual badges/icons accidentally included by the model while keeping
    common gamertag characters such as spaces, hyphens, underscores and dots.
    """
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"[\uFE00-\uFE0F]", "", text)

    chars: list[str] = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch.isalnum() or ch in {" ", "_", "-", ".", "'"}:
            chars.append(ch)
        elif cat.startswith("M"):
            continue
        elif ch.isspace():
            chars.append(" ")

    clean = "".join(chars)
    clean = re.sub(r"\s+", " ", clean).strip(" ._-")
    return clean or text


def normalize_weather(value: str | None) -> str:
    """Return the supported weather label used by cache/report code."""
    text = str(value or "").strip().lower()
    if text in {"rain", "wet", "chuva", "molhado", "raining"}:
        return "rain"
    if text in {"dry", "seco", "clear", "sunny"}:
        return "dry"
    return "unknown"


# ── Temperature ───────────────────────────────────────────────────────────────

def fahrenheit_to_celsius(tf: float | int | None,
                           temp_min: float = 40.0,
                           temp_max: float = 140.0) -> float | None:
    """
    Convert °F to °C with sanity-range validation.
    Returns None when the value is outside the plausible track-temperature
    window (defaults: 40–140 °F, i.e. roughly 4–60 °C).
    """
    if tf is None:
        return None
    try:
        val = float(str(tf).replace(",", "."))
        if temp_min <= val <= temp_max:
            return round((val - 32.0) * 5.0 / 9.0, 1)
    except (ValueError, TypeError):
        pass
    return None


# ── Class extraction ──────────────────────────────────────────────────────────

def extract_class_letter(cl_field: str) -> str:
    """
    Extract the single class letter from the LLM's cl field.

    Handles both formats:
      - "692 A"  (number and letter separated by space)
      - "692A"   (number and letter concatenated)
      - "A"      (bare letter)
    Falls back to "Unknown" when the field does not match expectations.
    """
    s = str(cl_field or "").strip().upper()
    if not s:
        return "Unknown"

    # Try last whitespace-separated token first ("692 A" → "A")
    tokens = s.split()
    last = tokens[-1]
    if re.match(r"^[A-Z]$", last):
        return last

    # Concatenated format: last character of an alphanumeric token
    # ("692A" / "PI400D" → "A" / "D")
    if re.match(r"^(?:PI)?\d+[A-Z]$", last):
        return last[-1]

    return "Unknown"


def detect_race_class(raw_entries: list[dict]) -> str:
    """
    Determine the race class from a list of entries (dicts with "ca" and
    "cl" keys).  Car names in "ca" must already be corrected by fix_car_name()
    so that TCR livery names match TCR_CARS exactly.

    Logic:
      1. If ≥ 30 % of the grid drives one of these cars  →  "TCR"
      2. If drivers span more than one class letter       →  "Mixed"
      3. Single class letter present                      →  that letter
      4. Nothing recognisable                             →  "Unknown"
    """
    if not raw_entries:
        return "Unknown"

    tcr_count = 0
    letters: set[str] = set()

    for entry in raw_entries:
        car = str(entry.get("ca", "")).strip()
        cl = str(entry.get("cl", "")).strip()

        # Car names are already corrected to match TCR_CARS
        if car in TCR_CARS:
            tcr_count += 1

        letter = extract_class_letter(cl)
        if letter != "Unknown":
            letters.add(letter)

    if raw_entries and (tcr_count / len(raw_entries)) >= 0.30:
        return "TCR"

    if len(letters) > 1:
        return "Mixed"

    return next(iter(letters), "Unknown")
