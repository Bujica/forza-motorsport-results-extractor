"""Dump golden domain vectors from the Python implementation for Rust tests.

Generates `forza-rust/fixtures/expected/domain_golden.json`. All driver names
are synthetic; no personal data is emitted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from forza.domain.lap import (
    detect_race_class,
    extract_class_letter,
    fahrenheit_to_celsius,
    format_lap_time_ms,
    is_dirty_lap,
    normalize_weather,
    parse_lap_time_ms,
    sanitize_driver_name,
    strip_dirty_symbol,
)
from forza.domain.normalizer import ReferenceData, fix_car_name, fix_track_name, load_reference_seed_text_data
from forza.domain.ordering import class_order_key, ordered_lap_key, track_order_key, track_order_map
from forza.domain.review_rules import (
    ambiguous_raw_track,
    driver_name_review_trigger,
    has_numeric_name_prefix,
    has_suspicious_name_symbol,
    track_suggestions,
)
from forza.domain.car_names import car_match_key

OUT = ROOT / "forza-rust" / "fixtures" / "expected" / "domain_golden.json"

LAP_INPUTS = [
    "1:23.456", "0:59.999", "12:34.567", "2:00.000",
    "23.456", "5.5", "45", "0:05.1", "1:07.12",
    "1:23.456 ▲", "1:23.456▲", "  1:23.456 ⚠ ", "1:23.456⚠️",
    "1:23.456 !", "1:23.4!56", "!1:23.456",
    "--", "---", "DNF", "dnq", "null", "None", "",
    "+0.500", "1:23.456+0.5", "abc", "1:2.345", "1:23.4567",
]

FORMAT_VALUES = [
    (83456, False), (59999, False), (754567, False), (120000, True),
    (1, False), (59999, True),
]

DIRTY_CHECKS = ["1:23.456 ▲", "1:23.456▲", "1:23.456 ⚠️", "22.1 △", "1:23.456", "", None, "▲"]

STRIP_INPUTS = ["1:23.456 ▲", "1:23.456▲", "1:23.456 ⚠️", "1:!23", "  ▲  ", "1:23.456 !", "1:!23 ▲"]

DRIVER_NAMES = [
    ("Bujica89",), ("  spaced   name  ",),
    ("Bad★Name!",), ("12 Fast Driver",),
    ("O'Neil-Smith_1",),
    ("Driver\u0301 combining",),
    ("Tab\tName",),
    ("★☆♪",),
    ("Dot . Name .",),
]

WEATHER_WORDS = ["rain", "wet", "chuva", "molhado", "raining",
                 "dry", "seco", "clear", "sunny", "Rain", "DRY", "", "fog"]

TEMPERATURES = [
    (72, 40.0, 140.0), ("72", 40.0, 140.0), ("72,5", 40.0, 140.0),
    (39, 40.0, 140.0), (141, 40.0, 140.0), (32, 32.0, 100.0), (None, 40.0, 140.0),
]

CLASS_FIELDS = ["692 A", "692A", "a", "PI400D", "pi400 d", "", None, "X", "123 XYZ", "P"]

GRIDS = [
    [],
    [{"ca": "Audi R8 LMS", "cl": "1 A"}, {"ca": "BMW M4", "cl": "2 A"}],
    [{"ca": "Audi R8 LMS", "cl": "1 A"}, {"ca": "BMW M4", "cl": "2 B"}],
    [{"ca": "#98 Elantra", "cl": "1 A"}, {"ca": "Honda #73 Civic", "cl": ""},
     {"ca": "MB #33 A45", "cl": ""}, {"ca": "BMW M4", "cl": "9 B"}],
    [{"ca": "Ford #17Focus ST", "cl": ""}],
    [{"ca": "Audi #1 RS 3 LMS", "cl": ""}, {"ca": "#66 Astra", "cl": "C"},
     {"ca": "#98 Veloster", "cl": ""}, {"ca": "Peugeot #7 308", "cl": ""},
     {"ca": "MG #20 MG6", "cl": ""}, {"ca": "VW #22 Golf GTI", "cl": ""}],
    [{"ca": "#98 Veloster", "cl": "C"}, {"ca": "BMW M4 GT3", "cl": "9 B"},
     {"ca": "#66 Astra", "cl": ""}],
    [{"ca": "Audi R8 LMS", "cl": ""}],
]


def build() -> dict:
    refs = load_reference_seed_text_data(ROOT / "tracks.txt", ROOT / "cars.txt")

    class _Row:
        def __init__(self, r: dict):
            self.track = r["track"]
            self.race_class = r["race_class"]
            self.weather = r["weather"]
            self.best_lap_ms = r["best_lap_ms"]
            self.driver = r["driver"]
            self.car = r["car"]

    track_fix_cases = [
        "Fuji Speedway GT", "fuji speedway gt", "Nurburgring Nordschleife",
        "Nürburgring Nordschleife", "nürburgring   nordschleife!",
        "Le Mans Full Circuit", "Le Mans Full Circut", "Le Mans Old Mulsane",
        "Le Mans", "Zandvoort", "ZANDVOORT", "Totally Made Up Track", "",
    ]
    car_fix_cases = [
        "Audi R8 LMS", "audi r8 lms", "audir8lms",
        "BMW M4 GT3", "bmw m4 gt3 evolutions", "Ferrari 296 GTB",
        "Unknown Car XYZ", "AudiR8LMS", "bmw m4 gt#",
    ]

    known_tracks = list(refs.tracks)
    suggestion_inputs = [
        "ambiguous layout: Le Mans",
        "Ambiguous layout)? : Fuji Speedway",
        "ambiguous layout:",
        "plain track name",
    ]

    order_list = sorted(known_tracks)[:50]
    omap = track_order_map(order_list)
    sample_rows = [
        {"track": order_list[0] if order_list else "T", "race_class": "A", "weather": "dry",
         "best_lap_ms": 90000, "driver": "Alpha", "car": "Car A"},
        {"track": "Mystery Track", "race_class": "B", "weather": None,
         "best_lap_ms": 80000, "driver": "beta", "car": "Car B"},
        {"track": order_list[-1] if order_list else "T", "race_class": "Unknown", "weather": "rain",
         "best_lap_ms": 120000, "driver": "Gamma", "car": "Car C"},
    ]
    ordered = []
    for r in sample_rows:
        k = ordered_lap_key(_Row(r), omap)
        ordered.append([
            list(k[0]) + list(k[1]) + [k[2], k[3], k[4], k[5]],
        ])

    return {
        "parse_lap_time_ms": [[i if i is not None else "__NONE__", parse_lap_time_ms(i)] for i in LAP_INPUTS],
        "format_lap_time_ms": {
            "values": [list(v) for v in FORMAT_VALUES],
            "results": [
                format_lap_time_ms(v[0], dirty=v[1]) for v in FORMAT_VALUES
            ],
        },
        "is_dirty_lap": [[repr(i) if not isinstance(i, str) else i, is_dirty_lap(i)] for i in DIRTY_CHECKS],
        "strip_dirty_symbol": [[c, strip_dirty_symbol(c)] for c in STRIP_INPUTS],
        "sanitize_driver_name": [[list(n)[0], sanitize_driver_name(list(n)[0])] for n in DRIVER_NAMES],
        "normalize_weather": [[w, normalize_weather(w)] for w in WEATHER_WORDS],
        "fahrenheit_to_celsius": [
            [str(t) if t is not None else "__NONE__", lo, hi, fahrenheit_to_celsius(t, lo, hi)]
            for t, lo, hi in TEMPERATURES
        ],
        "extract_class_letter": [[c if c is not None else "__NONE__", extract_class_letter(c)] for c in CLASS_FIELDS],
        "detect_race_class": [[g, detect_race_class(g)] for g in GRIDS],
        "car_match_key": [
            ["Toyota Corolla '74", car_match_key("Toyota Corolla '74")],
            ["Toyota Corolla 1974", car_match_key("Toyota Corolla 1974")],
            ["Elemental Rp1 ’19", car_match_key("Elemental Rp1 ’19")],
            ["Mini Cooper `65", car_match_key("Mini Cooper `65")],
            ["Audi R8 LMS evoluzione", car_match_key("Audi R8 LMS evoluzione")],
        ],
        "fix_track_name": [[c, fix_track_name(c, refs)] for c in track_fix_cases],
        "fix_car_name": [[c, fix_car_name(c, refs)] for c in car_fix_cases],
        "review_triggers": [
            ["   ", driver_name_review_trigger("   ")],
            ["12 Fast", driver_name_review_trigger("12 Fast")],
            ["1234 Slow", driver_name_review_trigger("1234 Slow")],
            ["Bad★Name", driver_name_review_trigger("Bad★Name")],
            ["Good-Name_1.", driver_name_review_trigger("Good-Name_1.")],
            ["", driver_name_review_trigger("")],
        ],
        "has_numeric_prefix": [["12 Fast", has_numeric_name_prefix("12 Fast")], ["1245 Fast", has_numeric_name_prefix("1245 Fast")]],
        "has_suspicious_symbol": [["Ok Name", has_suspicious_name_symbol("Ok Name")], ["No★pe", has_suspicious_name_symbol("No★pe")]],
        "ambiguous_raw_track": [
            ["ambiguous layout: Le Mans", ambiguous_raw_track("ambiguous layout: Le Mans")],
            ["Ambiguous Layout)? : Fuji Speedway", ambiguous_raw_track("Ambiguous Layout)? : Fuji Speedway")],
            ["nothing here", ambiguous_raw_track("nothing here")],
        ],
        "track_suggestions": [[s, track_suggestions(s, known_tracks)] for s in suggestion_inputs],
        "ordering_keys": {
            "order_map_input": order_list,
            "rows": sample_rows,
            "keys": ordered,
        },
    }


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"golden vectors -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
