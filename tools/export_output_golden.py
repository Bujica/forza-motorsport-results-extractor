"""Generate output goldens from the REAL Python implementations:
- CSV bytes via forza.output.csv.export_csv
- PDF content plan (data map + ordering + symbols) mirroring
  forza/output/pdf.py::_build_data_map and the rendering loop
All values are synthetic; nothing personal is emitted.
"""

from __future__ import annotations

import base64
import io
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from forza.config import CLASS_COLORS
from forza.domain import class_order_key, ordered_lap_key, track_order_key, track_order_map
from forza.output.csv import _CSV_FIELDS, export_csv

OUT_DIR = ROOT / "forza-rust" / "fixtures" / "expected"
TRACKS_FILE = ROOT / "tracks.txt"

# Synthetic clean-flat rows shaped like ExportLap (only fields used by outputs).
ROWS = [
    dict(track="Fuji Speedway", race_class="A", weather="dry",
         temp_f=80.0, temp_c=26.7, driver="Rival One", car="BMW M4 GT3",
         best_lap="1:29.000", best_lap_ms=89000, dirty=False,
         source_file=None, race_date=None, image_format=None,
         width_px=None, height_px=None),
    dict(track="Fuji Speedway", race_class="A", weather="dry",
         temp_f=80.0, temp_c=26.7, driver="TestDriver", car="Audi R8 LMS",
         best_lap="1:30.500 ▲", best_lap_ms=90500, dirty=True,
         source_file="shot_player.png", race_date=date(2026, 8, 1),
         image_format="png", width_px=3840, height_px=2160),
    dict(track="Le Mans Full Circuit", race_class="TCR", weather="rain",
         temp_f=61.0, temp_c=16.1, driver="TestDriver", car="Honda #73 Civic",
         best_lap="2:05.123", best_lap_ms=125123, dirty=False,
         source_file="shot_lm.png", race_date=date(2026, 7, 20),
         image_format="jpeg", width_px=1920, height_px=1080),
]

GAMERTAG = "TestDriver"


class Row:
    def __init__(self, d):
        self.__dict__.update(d)


def build_csv_golden() -> str:
    buf_in = Path(OUT_DIR / "_tmp_csv.csv")
    n = export_csv([Row(r) for r in ROWS], buf_in)
    assert n == len(ROWS)
    data = buf_in.read_bytes()
    buf_in.unlink()
    return base64.b64encode(data).decode()


def build_pdf_plan_golden() -> dict:
    # Mirror pdf.py::_build_data_map (internal pass only).
    gamertag_lower = GAMERTAG.lower()
    data_map: dict[str, dict[str, list[dict]]] = {}
    for raw in ROWS:
        r = Row(raw)
        track = r.track or "Unknown"
        cls = r.race_class
        row = {
            "driver": r.driver,
            "car": r.car,
            "time_str": r.best_lap,
            "time_sec": r.best_lap_ms / 1000,
            "temp": r.temp_c,
            "weather": r.weather,
            "dirty": r.dirty,
            "mine": r.driver.lower() == gamertag_lower,
            "external": False,
            "file": r.source_file,
        }
        data_map.setdefault(track, {}).setdefault(cls, []).append(row)

    for track in data_map:
        for cls in data_map[track]:
            data_map[track][cls].sort(key=lambda x: (x["time_sec"], not x["mine"]))

    track_order: list[str] = [
        line.strip() for line in TRACKS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    order_index = track_order_map(track_order)
    sorted_tracks = sorted(data_map, key=lambda t: track_order_key(t, order_index))

    sections = []
    for track in sorted_tracks:
        classes_sorted = sorted(data_map[track], key=class_order_key)
        tables = []
        for cls in classes_sorted:
            rows = data_map[track][cls]
            if not rows:
                continue
            color_hex = CLASS_COLORS.get(cls, "#000000")
            tables.append({
                "class": cls,
                "color_hex": color_hex,
                "rows": [
                    {
                        "driver": x["driver"],
                        "car": x["car"],
                        "time_str": x["time_str"],
                        "time_ms": int(x["time_sec"] * 1000),
                        "dirty": x["dirty"],
                        "mine": x["mine"],
                        "temp": x["temp"],
                    }
                    for x in rows
                ],
            })
        sections.append({"track": track, "tables": tables})

    total_tracks = len(data_map)
    total_classes = sum(len(c) for c in data_map.values())
    total_laps = sum(len(rows) for t in data_map.values() for rows in t.values())
    return {
        "gamertag": GAMERTAG,
        "stats": {"tracks": total_tracks, "classes": total_classes, "laps": total_laps},
        "sections": sections,
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "csv_b64": build_csv_golden(),
        "pdf_plan": build_pdf_plan_golden(),
        "csv_fields": _CSV_FIELDS,
    }
    target = OUT_DIR / "output_golden.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
