from __future__ import annotations

from pathlib import Path

from forza.application import db_doctor_service
from forza.application.db_doctor import status_checks
from forza.application.db_doctor.contracts import DbDoctorCheck
from forza.application.db_doctor.status_checks import invalid_status_values_check


ROOT = Path(__file__).resolve().parents[1]


def test_status_vocabulary_check_moves_out_of_service_surface() -> None:
    service_source = (ROOT / "forza" / "application" / "db_doctor_service.py").read_text(encoding="utf-8")
    status_source = (ROOT / "forza" / "application" / "db_doctor" / "status_checks.py").read_text(encoding="utf-8")

    assert "invalid_status_values_check(session)" in service_source
    assert '"invalid_status_values"' not in service_source
    assert "'invalid_status_values'" not in service_source

    assert "def invalid_status_values_check" in status_source
    assert "invalid_status_values" in status_source
    assert "vocabulary_check_constraints_missing" not in status_source


def test_status_check_function_preserves_key_and_severity(monkeypatch) -> None:
    def fake_check_sql(_session, *, key, detail, sql, severity="error"):
        return DbDoctorCheck(key, severity, 4, detail)

    monkeypatch.setattr(status_checks, "_check_sql", fake_check_sql)

    check = invalid_status_values_check(object())

    assert check.key == "invalid_status_values"
    assert check.severity == "error"
    assert check.count == 4
    assert check.detail == "Persisted lifecycle/status fields must use the DB vNext vocabulary."


def test_db_doctor_service_compatibility_exports_status_check_helper() -> None:
    assert db_doctor_service.invalid_status_values_check is invalid_status_values_check
