from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from forza.output.csv import export_csv
from forza.output.pdf import _build_data_map
from forza.schemas import ExportLap


def _lap(
    *,
    source_file: str,
    track: str = "Mugello Circuit Full Circuit",
    race_class: str = "A",
    driver: str = "Bujica89",
    best_lap: str = "01:00.000",
    best_lap_ms: int = 60000,
    dirty: bool = False,
) -> ExportLap:
    return ExportLap(
        image_file_id=f"img-{source_file}",
        source_file=source_file,
        file_hash=f"hash-{source_file}",
        lap_index=0,
        semantic_name=source_file,
        race_datetime=None,
        race_date=date(2026, 6, 1),
        image_format="png",
        width_px=1600,
        height_px=900,
        track=track,
        race_class=race_class,
        weather="dry",
        temp_f=77.0,
        temp_c=25.0,
        driver=driver,
        car="Car",
        car_class=race_class,
        best_lap=best_lap,
        best_lap_ms=best_lap_ms,
        dirty=dirty,
        is_best_lap=True,
    )


def test_export_csv_writes_stable_relational_headers_and_rows(tmp_path: Path) -> None:
    out = tmp_path / "exports" / "results.csv"

    rows = export_csv(
        [
            _lap(source_file="first.png", best_lap="00:59.500", best_lap_ms=59500),
            _lap(source_file="second.png", driver="Rival", dirty=True),
        ],
        out,
    )

    assert rows == 2
    with out.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        exported = list(reader)

    assert exported[0] == [
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
    assert exported[1][5:11] == ["Bujica89", "Car", "00:59.500", "59500", "False", "first.png"]
    assert exported[2][5:11] == ["Rival", "Car", "01:00.000", "60000", "True", "second.png"]


def test_pdf_data_map_groups_and_sorts_rows_without_visual_snapshot() -> None:
    data_map = _build_data_map(
        [
            _lap(source_file="rival.png", driver="Rival", best_lap="01:00.000", best_lap_ms=60000),
            _lap(source_file="mine.png", driver="Bujica89", best_lap="01:00.000", best_lap_ms=60000),
        ],
        gamertag="Bujica89",
        external_records=[
            {
                "track": "Mugello Circuit Full Circuit",
                "race_class": "A",
                "driver": "External Pro",
                "car": "External Car",
                "best_lap": "01:01.000",
                "best_lap_ms": 61000,
            },
            {
                "track": "Mugello Circuit Full Circuit",
                "race_class": "A",
                "driver": "Broken External",
                "car": "External Car",
                "best_lap": "bad",
                "best_lap_ms": "not-ms",
            },
        ],
    )

    bucket = data_map["Mugello Circuit Full Circuit"]["A"]

    assert [row["driver"] for row in bucket] == ["Bujica89", "Rival", "External Pro"]
    assert [row["time_sec"] for row in bucket] == [60.0, 60.0, 61.0]
    assert bucket[0]["mine"] is True
    assert bucket[1]["external"] is False
    assert bucket[2]["external"] is True
    assert bucket[2]["file"] is None
