from __future__ import annotations

from pathlib import Path

from forza.application import db_doctor_service
from forza.application.db_doctor.sqlite_checks import (
    foreign_key_violations_check,
    schema_head_check,
    sqlite_integrity_check,
)


ROOT = Path(__file__).resolve().parents[1]


def test_schema_head_check_returns_none_for_current_schema() -> None:
    assert schema_head_check("current") is None


def test_schema_head_check_preserves_legacy_report_shape_for_non_current_schema() -> None:
    check = schema_head_check("missing")

    assert check is not None
    assert check.key == "schema_head"
    assert check.severity == "error"
    assert check.count == 1
    assert check.detail == "Database schema is not at Alembic head."


def test_sqlite_integrity_checks_move_out_of_service_surface() -> None:
    service_source = (ROOT / "forza" / "application" / "db_doctor_service.py").read_text(encoding="utf-8")
    checks_source = (ROOT / "forza" / "application" / "db_doctor" / "sqlite_checks.py").read_text(encoding="utf-8")

    assert "schema_head_check(schema_state)" in service_source
    assert "sqlite_integrity_check(session)" in service_source
    assert "foreign_key_violations_check(session)" in service_source

    assert "def _sqlite_integrity_errors" not in service_source
    assert "def _foreign_key_violations" not in service_source
    assert "def _sqlite_integrity_errors" in checks_source
    assert "def _foreign_key_violations" in checks_source


def test_sqlite_check_functions_preserve_keys_and_severity(monkeypatch) -> None:
    monkeypatch.setattr(
        "forza.application.db_doctor.sqlite_checks._sqlite_integrity_errors",
        lambda _session: 2,
    )
    monkeypatch.setattr(
        "forza.application.db_doctor.sqlite_checks._foreign_key_violations",
        lambda _session: 3,
    )

    integrity = sqlite_integrity_check(object())
    foreign_keys = foreign_key_violations_check(object())

    assert (integrity.key, integrity.severity, integrity.count) == (
        "sqlite_integrity_check",
        "error",
        2,
    )
    assert (foreign_keys.key, foreign_keys.severity, foreign_keys.count) == (
        "foreign_key_violations",
        "error",
        3,
    )


def test_db_doctor_service_compatibility_exports_sqlite_check_helpers() -> None:
    assert db_doctor_service.schema_head_check is schema_head_check
    assert db_doctor_service.sqlite_integrity_check is sqlite_integrity_check
    assert db_doctor_service.foreign_key_violations_check is foreign_key_violations_check
