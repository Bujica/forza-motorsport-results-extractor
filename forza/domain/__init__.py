"""Pure domain helpers shared by CLI, GUI, reports, and application services."""

from .lap import (
    TCR_CARS,
    detect_race_class,
    extract_class_letter,
    fahrenheit_to_celsius,
    format_lap_time_ms,
    is_dirty_lap,
    normalize_weather,
    parse_lap_time,
    parse_lap_time_ms,
    sanitize_driver_name,
    strip_dirty_symbol,
)
from .normalizer import ReferenceData, fix_car_name, fix_track_name, load_reference_seed_text_data
from .ordering import LapRowLike, class_order_key, ordered_lap_key, track_order_map, track_order_key
from .race_class import CLASS_ORDER
from .review_rules import (
    ambiguous_raw_track,
    has_suspicious_name_symbol,
    track_key,
    track_suggestions,
)
from .text_utils import load_nonempty_lines, normalize_ascii_compare, normalize_whitespace_lower, strip_dirty_lap_marker

__all__ = [
    "CLASS_ORDER",
    "LapRowLike",
    "TCR_CARS",
    "ReferenceData",
    "ambiguous_raw_track",
    "class_order_key",
    "detect_race_class",
    "extract_class_letter",
    "fahrenheit_to_celsius",
    "fix_car_name",
    "fix_track_name",
    "format_lap_time_ms",
    "has_suspicious_name_symbol",
    "is_dirty_lap",
    "load_nonempty_lines",
    "load_reference_seed_text_data",
    "normalize_ascii_compare",
    "normalize_weather",
    "normalize_whitespace_lower",
    "ordered_lap_key",
    "parse_lap_time",
    "parse_lap_time_ms",
    "sanitize_driver_name",
    "strip_dirty_lap_marker",
    "strip_dirty_symbol",
    "track_order_key",
    "track_order_map",
    "track_key",
    "track_suggestions",
]
