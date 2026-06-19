import pytest
from forza.domain.lap import (
    parse_lap_time,
    parse_lap_time_ms,
    format_lap_time_ms,
    is_dirty_lap,
    extract_class_letter,
    detect_race_class,
    strip_dirty_symbol,
    fahrenheit_to_celsius,
    sanitize_driver_name,
    normalize_weather,
)


# ── strip_dirty_symbol ────────────────────────────────────────────────────────

def test_strip_dirty_symbol_with_space():
    assert strip_dirty_symbol("1:23.456 ▲") == "1:23.456"


def test_strip_dirty_symbol_no_space():
    assert strip_dirty_symbol("1:23.456▲") == "1:23.456"


def test_strip_dirty_symbol_clean():
    assert strip_dirty_symbol("1:23.456") == "1:23.456"


def test_strip_dirty_symbol_leading_symbol_not_stripped():
    # strip_dirty_symbol calls .strip() first, so outer whitespace is removed.
    # The leading ▲ is NOT at the end of the string, so it is preserved.
    # Input after .strip(): "▲ 1:23.456 ▲" → trailing " ▲" removed → "▲ 1:23.456"
    assert strip_dirty_symbol("  ▲ 1:23.456 ▲  ") == "▲ 1:23.456"


def test_strip_dirty_symbol_multiple_symbols():
    assert strip_dirty_symbol("1:23.456 ▲⚠") == "1:23.456"


def test_strip_dirty_symbol_warning_emoji():
    assert strip_dirty_symbol("1:23.456⚠️") == "1:23.456"


# ── parse_lap_time ────────────────────────────────────────────────────────────

def test_parse_lap_time_normal():
    assert parse_lap_time("1:23.456") == pytest.approx(83.456)


def test_parse_lap_time_dirty_with_space():
    assert parse_lap_time("1:23.456 ▲") == pytest.approx(83.456)


def test_parse_lap_time_dirty_no_space():
    assert parse_lap_time("1:23.456▲") == pytest.approx(83.456)


def test_parse_lap_time_seconds_only():
    assert parse_lap_time("59.999") == pytest.approx(59.999)


def test_parse_lap_time_zero_minutes():
    # "0:45.123" — zero in the minutes field is valid
    assert parse_lap_time("0:45.123") == pytest.approx(45.123)


def test_parse_lap_time_large_minutes():
    # Long Nurburgring-style lap times
    assert parse_lap_time("7:34.149") == pytest.approx(454.149)


def test_parse_lap_time_no_milliseconds():
    assert parse_lap_time("1:23") == pytest.approx(83.0)


def test_parse_lap_time_invalid():
    assert parse_lap_time("DNF") is None
    assert parse_lap_time("--") is None
    assert parse_lap_time("") is None
    assert parse_lap_time(None) is None


def test_parse_lap_time_dnq():
    assert parse_lap_time("DNQ") is None


def test_parse_lap_time_gap():
    # Gap times (e.g. "+1:23.456") must not be treated as absolute times
    assert parse_lap_time("1:23.456+0.5") is None


def test_parse_lap_time_ms_is_canonical_internal_time():
    assert parse_lap_time_ms("1:23.456") == 83_456
    assert parse_lap_time_ms("1:23.456 ▲") == 83_456
    assert parse_lap_time_ms("59.9") == 59_900
    assert parse_lap_time_ms("7:34.149") == 454_149


def test_parse_lap_time_ms_rejects_invalid_and_gaps():
    assert parse_lap_time_ms("DNF") is None
    assert parse_lap_time_ms("1:23.456+0.5") is None
    assert parse_lap_time_ms(None) is None


def test_format_lap_time_ms():
    assert format_lap_time_ms(83_456) == "1:23.456"
    assert format_lap_time_ms(83_456, dirty=True) == "1:23.456 ▲"
    assert format_lap_time_ms(454_149) == "7:34.149"


def test_format_lap_time_ms_rejects_non_positive_values():
    with pytest.raises(ValueError):
        format_lap_time_ms(0)


# ── is_dirty_lap ──────────────────────────────────────────────────────────────

def test_is_dirty_lap_with_space():
    assert is_dirty_lap("1:23.456 ▲") is True


def test_is_dirty_lap_no_space():
    assert is_dirty_lap("1:23.456▲") is True


def test_is_dirty_lap_clean():
    assert is_dirty_lap("1:23.456") is False


def test_is_dirty_lap_none():
    assert is_dirty_lap(None) is False


def test_is_dirty_lap_warning_emoji():
    assert is_dirty_lap("1:23.456⚠️") is True


# ── driver/weather normalisation ──────────────────────────────────────────────

def test_sanitize_driver_name_removes_visual_badges():
    assert sanitize_driver_name("Whiteboyrick221⚔️") == "Whiteboyrick221"
    assert sanitize_driver_name("staring contest 👑") == "staring contest"


def test_sanitize_driver_name_keeps_common_gamertag_chars():
    assert sanitize_driver_name("A_B-C.D 'Racer'") == "A_B-C.D 'Racer'"


def test_normalize_weather():
    assert normalize_weather("rain") == "rain"
    assert normalize_weather("wet") == "rain"
    assert normalize_weather("dry") == "dry"
    assert normalize_weather("not visible") == "unknown"


# ── extract_class_letter ──────────────────────────────────────────────────────

def test_extract_class_letter_spaced():
    assert extract_class_letter("692 A") == "A"


def test_extract_class_letter_concatenated():
    # New format: number and letter with no space
    assert extract_class_letter("692A") == "A"


def test_extract_class_letter_high_pi_spaced():
    assert extract_class_letter("710 S") == "S"


def test_extract_class_letter_high_pi_concatenated():
    assert extract_class_letter("710S") == "S"


def test_extract_class_letter_compact_pi_prefix():
    assert extract_class_letter("PI400D") == "D"


def test_extract_class_letter_bare():
    assert extract_class_letter("A") == "A"


def test_extract_class_letter_empty():
    assert extract_class_letter("") == "Unknown"


def test_extract_class_letter_pi_prefix():
    # The active prompt asks for the PI prefix when visible.
    assert extract_class_letter("PI 692 A") == "A"


@pytest.mark.parametrize("raw", [
    "PI400D",
    "PI 400 D",
    "400D",
    "400 D",
    "D",
])
def test_extract_class_letter_common_pi_variants(raw):
    assert extract_class_letter(raw) == "D"


def test_extract_class_letter_non_letter_token():
    # Last token is not a single letter or ddd+letter → Unknown
    assert extract_class_letter("123") == "Unknown"


# ── detect_race_class ─────────────────────────────────────────────────────────

def test_detect_race_class_tcr():
    entries = [
        {"ca": "MG #20 MG6",      "cl": "TCR"},
        {"ca": "VW #22 Golf GTI", "cl": "TCR"},
    ]
    assert detect_race_class(entries) == "TCR"


def test_detect_race_class_tcr_threshold():
    # 1 out of 3 = 33 % — still above the 30 % threshold
    entries = [
        {"ca": "MG #20 MG6", "cl": "TCR"},
        {"ca": "Carro A",    "cl": "500 C"},
        {"ca": "Carro B",    "cl": "510 C"},
    ]
    assert detect_race_class(entries) == "TCR"


def test_detect_race_class_below_tcr_threshold():
    # 1 out of 4 = 25 % — below threshold, class letters decide
    entries = [
        {"ca": "MG #20 MG6", "cl": "TCR"},
        {"ca": "Carro A",    "cl": "500 C"},
        {"ca": "Carro B",    "cl": "510 C"},
        {"ca": "Carro C",    "cl": "520 C"},
    ]
    assert detect_race_class(entries) == "C"


def test_detect_race_class_mixed():
    entries = [
        {"ca": "Carro A", "cl": "692 A"},
        {"ca": "Carro S", "cl": "710 S"},
    ]
    assert detect_race_class(entries) == "Mixed"


def test_detect_race_class_single():
    entries = [
        {"ca": "Carro A", "cl": "800 S"},
        {"ca": "Carro B", "cl": "750 S"},
    ]
    assert detect_race_class(entries) == "S"


def test_detect_race_class_empty():
    assert detect_race_class([]) == "Unknown"


# ── fahrenheit_to_celsius ─────────────────────────────────────────────────────

def test_fahrenheit_to_celsius_typical():
    # 77 °F = 25 °C
    assert fahrenheit_to_celsius(77) == pytest.approx(25.0, abs=0.1)


def test_fahrenheit_to_celsius_freezing():
    # 32 °F = 0 °C, but below temp_min_f=40 → None
    assert fahrenheit_to_celsius(32) is None


def test_fahrenheit_to_celsius_boundary_low():
    # Exactly at default minimum (40 °F) — should be valid
    result = fahrenheit_to_celsius(40)
    assert result is not None
    assert result == pytest.approx(4.4, abs=0.1)


def test_fahrenheit_to_celsius_boundary_high():
    # Exactly at default maximum (140 °F) — should be valid
    result = fahrenheit_to_celsius(140)
    assert result is not None
    assert result == pytest.approx(60.0, abs=0.1)


def test_fahrenheit_to_celsius_out_of_range_high():
    assert fahrenheit_to_celsius(200) is None


def test_fahrenheit_to_celsius_none():
    assert fahrenheit_to_celsius(None) is None


def test_fahrenheit_to_celsius_custom_range():
    # Custom range that accepts 32 °F
    result = fahrenheit_to_celsius(32, temp_min=20.0, temp_max=100.0)
    assert result == pytest.approx(0.0, abs=0.1)


def test_fahrenheit_to_celsius_string_input():
    # The function should accept numeric strings (comma or dot decimal)
    assert fahrenheit_to_celsius("77") == pytest.approx(25.0, abs=0.1)
