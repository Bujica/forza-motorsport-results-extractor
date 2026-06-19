"""
Export the clean cache to external formats for analysis and backup.

Currently supported:
  CSV — flat table, one row per lap entry, suitable for Excel / Google Sheets.

Usage (CLI):
    python -m forza export               # CSV to output/exports/results.csv
    python -m forza export --format csv  # explicit format
    python -m forza export --out PATH    # custom output path

Programmatic:
    from forza.output import export_csv
    export_csv(cleaned_results, Path("output/exports/results.csv"))
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from ..schemas import ExportLap

log = logging.getLogger("forza")


# ── CSV export ────────────────────────────────────────────────────────────────

_CSV_FIELDS = [
    "track",
    "race_class",
    "weather",
    "temp_f",
    "temp_c",
    "driver",
    "car",
    "best_lap",
    "best_lap_ms",
    "dirty",
    "source_file",
    "race_date",
    "image_format",
    "width_px",
    "height_px",
]


def export_csv(results: list[ExportLap], out_path: Path) -> int:
    """
    Write a flat CSV from relational export rows.

    Each row represents one persisted lap entry. Session-level fields (track,
    class, weather, temperature) are repeated by the database read model.

    Parameters
    ----------
    results  : Relational best-lap export, usually from DatabaseService.list_clean_flat().
    out_path : Destination path; parent directory is created if necessary.

    Returns the number of rows written (0 if nothing to export).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for r in results:
        rows.append({
            "track": r.track,
            "race_class": r.race_class,
            "weather": r.weather,
            "temp_f": r.temp_f if r.temp_f is not None else "",
            "temp_c": r.temp_c if r.temp_c is not None else "",
            "driver": r.driver,
            "car": r.car,
            "best_lap": r.best_lap,
            "best_lap_ms": r.best_lap_ms,
            "dirty": r.dirty,
            "source_file": r.source_file,
            "race_date": r.race_date.isoformat() if r.race_date else "",
            "image_format": r.image_format or "",
            "width_px": r.width_px or "",
            "height_px": r.height_px or "",
        })

    if not rows:
        log.warning("[export] No data to export")
        return 0

    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    log.info(f"[export] CSV written: {out_path}  ({len(rows)} rows)")
    return len(rows)

