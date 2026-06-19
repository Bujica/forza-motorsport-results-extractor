from __future__ import annotations

from pathlib import Path

import pytest

from forza.application import db_doctor_service
from forza.application.db_doctor import DbDoctorCheck, DbDoctorCheckRegistry, DbDoctorReport


ROOT = Path(__file__).resolve().parents[1]


def test_db_doctor_contracts_are_reexported_from_service_surface() -> None:
    assert db_doctor_service.DbDoctorCheck is DbDoctorCheck
    assert db_doctor_service.DbDoctorReport is DbDoctorReport

    check = DbDoctorCheck(
        key="example",
        severity="error",
        count=0,
        detail="Example detail.",
    )
    report = DbDoctorReport(
        database_file=Path("db.sqlite3"),
        schema_state="current",
        checks=[check],
    )

    assert check.ok
    assert report.ok


def test_db_doctor_registry_preserves_order_and_rejects_duplicate_keys() -> None:
    registry = DbDoctorCheckRegistry()

    def first(_session):
        return [DbDoctorCheck("first", "error", 0, "first")]

    def second(_session):
        return [DbDoctorCheck("second", "warning", 1, "second")]

    registry.register("first", first)
    registry.register("second", second)

    assert [registered.key for registered in registry.checks()] == ["first", "second"]
    assert registry.checks()[0].check is first
    assert registry.checks()[1].check is second

    with pytest.raises(ValueError, match="Duplicate DB Doctor check key"):
        registry.register("first", first)


def test_db_doctor_service_no_longer_owns_contract_dataclasses() -> None:
    source = (ROOT / "forza" / "application" / "db_doctor_service.py").read_text(encoding="utf-8")

    assert "from .db_doctor.contracts import DbDoctorCheck, DbDoctorReport" in source
    assert "class DbDoctorCheck:" not in source
    assert "class DbDoctorReport:" not in source
