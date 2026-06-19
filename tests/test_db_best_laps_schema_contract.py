from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from forza.application import DatabaseService
from forza.application.external_record_service import ExternalRecordService
from forza.application.gui_database_state import apply_database_upgrade
from forza.db.migrate import DatabaseSchemaState, upgrade_database


def test_fresh_schema_keeps_best_laps_as_indexed_table_contract(tmp_path: Path) -> None:
    db_path = tmp_path / "forza.sqlite3"

    upgrade_database(db_path)

    with sqlite3.connect(db_path) as connection:
        views = _sqlite_names(connection, "view")
        indexes = _sqlite_names(connection, "index")

    assert "v_best_laps" not in views
    assert ("v_model" + "_debug") not in views
    assert "v_run_attempt_summary" not in views
    assert "idx_lap_records_best_gui_order" in indexes
    assert "idx_external_lap_records_active_order" in indexes


def test_gui_created_database_seeds_references_for_external_import(tmp_path: Path) -> None:
    db_path = tmp_path / "forza.sqlite3"

    state = apply_database_upgrade(db_path)

    assert state.opened is True
    assert state.state == DatabaseSchemaState.CURRENT
    with DatabaseService(db_path) as database:
        tracks = database.list_reference_tracks()
        cars = database.list_reference_cars()
        assert tracks
        assert cars

        csv_path = tmp_path / "external.csv"
        _write_external_csv(csv_path, track=tracks[0], car=cars[0])

        result = ExternalRecordService(aliases_file=tmp_path / "missing_aliases.json").import_to_db(
            database,
            csv_path,
        )
        persisted = database.list_external_records()

    assert result.total_rows == 1
    assert result.unmapped_tracks == 0
    assert result.invalid_laps == 0
    assert len(persisted) == 1
    assert persisted[0].track == tracks[0]
    assert persisted[0].car == cars[0]
    assert persisted[0].best_lap_ms == 56092


def _sqlite_names(connection: sqlite3.Connection, object_type: str) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = ?",
            (object_type,),
        )
    }


def _write_external_csv(path: Path, *, track: str, car: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Track", "Class", "Gamertag", "Vehicle", "Laptime"])
        writer.writeheader()
        writer.writerow(
            {
                "Track": track,
                "Class": "D",
                "Gamertag": "ExternalDriver",
                "Vehicle": car,
                "Laptime": "00:56.092",
            }
        )
