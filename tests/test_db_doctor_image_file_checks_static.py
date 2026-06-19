from __future__ import annotations

from pathlib import Path
import importlib

from forza.application import db_doctor_service
from forza.application.db_doctor.contracts import DbDoctorCheck
from forza.application.db_doctor.image_file_checks import (
    best_lap_status_checks,
    best_lap_value_checks,
    lap_parent_checks,
    image_file_checks,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE = importlib.import_module("forza.application.db_doctor.image_file_checks")


def test_image_file_and_best_lap_checks_move_out_of_service_surface() -> None:
    service_source = (ROOT / "forza" / "application" / "db_doctor_service.py").read_text(encoding="utf-8")
    module_source = (ROOT / "forza" / "application" / "db_doctor" / "image_file_checks.py").read_text(encoding="utf-8")

    assert "*image_file_checks(session)" in service_source
    assert "*best_lap_value_checks(session)" in service_source
    assert "*lap_parent_checks(session)" in service_source
    assert "*best_lap_status_checks(session)" in service_source

    moved_keys = (
        "images_missing_metadata",
        "available_image_path_conflicts",
        "available_images_missing_files",
        "available_images_hash_mismatch",
        "best_laps_without_positive_ms",
        "clean_lap_contains_dirty_marker",
        "laps_without_image_file",
        "lap_parent_mismatch",
        "best_lap_status_divergent",
        "best_lap_status_stale_pending",
    )
    for key in moved_keys:
        assert f'"{key}"' not in service_source
        assert f"'{key}'" not in service_source
        assert key in module_source

    assert "def _available_image_file_checks" not in service_source
    assert "def _best_status_divergence" not in service_source
    assert "def _pending_images_with_clean_laps" not in service_source


def test_image_file_and_best_lap_check_functions_preserve_key_order(monkeypatch) -> None:
    def fake_check_sql(_session, *, key, detail, sql, severity="error", count_groups=False):
        return DbDoctorCheck(key, severity, 0, detail)

    monkeypatch.setattr(MODULE, "_check_sql", fake_check_sql)
    monkeypatch.setattr(MODULE, "_count", lambda _session, _query: 3)
    monkeypatch.setattr(MODULE, "_available_image_file_checks", lambda _session: (1, 2))
    monkeypatch.setattr(MODULE, "_best_status_divergence", lambda _session: 4)
    monkeypatch.setattr(MODULE, "_pending_images_with_clean_laps", lambda _session: 5)

    assert [check.key for check in image_file_checks(object())] == [
        "images_missing_metadata",
        "available_image_path_conflicts",
        "available_images_missing_files",
        "available_images_hash_mismatch",
    ]
    assert [check.key for check in best_lap_value_checks(object())] == [
        "best_laps_without_positive_ms",
        "clean_lap_contains_dirty_marker",
    ]
    assert [check.key for check in lap_parent_checks(object())] == [
        "laps_without_image_file",
        "lap_parent_mismatch",
    ]
    assert [check.key for check in best_lap_status_checks(object())] == [
        "best_lap_status_divergent",
        "best_lap_status_stale_pending",
    ]


def test_db_doctor_service_compatibility_exports_image_file_check_helpers() -> None:
    assert db_doctor_service.image_file_checks is image_file_checks
    assert db_doctor_service.best_lap_value_checks is best_lap_value_checks
    assert db_doctor_service.lap_parent_checks is lap_parent_checks
    assert db_doctor_service.best_lap_status_checks is best_lap_status_checks
