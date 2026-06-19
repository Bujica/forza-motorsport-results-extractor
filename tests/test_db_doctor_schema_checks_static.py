from __future__ import annotations

import importlib
from pathlib import Path

from forza.application.db_doctor.schema_checks import schema_drift_checks


ROOT = Path(__file__).resolve().parents[1]
MODULE = importlib.import_module("forza.application.db_doctor.schema_checks")


def _private_helper_name(*parts: str) -> str:
    return "".join(parts)


_PRIVATE_HELPERS = (
    _private_helper_name("_vocabulary", "_check_constraints_missing"),
    _private_helper_name("_schema", "_column_drift"),
    _private_helper_name("_schema", "_server_default_drift"),
    _private_helper_name("_frozen", "_schema_sql_drift"),
    _private_helper_name("_sqlite", "_schema_objects"),
    _private_helper_name("_normalize", "_schema_sql"),
    _private_helper_name("_sqlite", "_identifier"),
    _private_helper_name("_add", "_vocabulary_check_constraints"),
)


def test_schema_drift_checks_move_out_of_service_surface() -> None:
    service_source = (ROOT / "forza" / "application" / "db_doctor_service.py").read_text(encoding="utf-8")
    schema_source = (ROOT / "forza" / "application" / "db_doctor" / "schema_checks.py").read_text(encoding="utf-8")

    assert "*schema_drift_checks(session)" in service_source
    assert service_source.count("*review_core_checks(session)") == 1

    moved_keys = (
        "vocabulary_check_constraints_missing",
        "schema_column_drift",
        "schema_server_default_drift",
        "frozen_schema_sql_drift",
    )
    for key in moved_keys:
        assert f'"{key}"' not in service_source
        assert f"'{key}'" not in service_source
        assert key in schema_source

    for helper in _PRIVATE_HELPERS:
        assert f"def {helper}" not in service_source
        assert f"def {helper}" in schema_source or hasattr(MODULE, helper)


def test_schema_column_drift_covers_reference_tables_and_quotes_identifiers() -> None:
    schema_source = (ROOT / "forza" / "application" / "db_doctor" / "schema_checks.py").read_text(encoding="utf-8")

    assert "ReferenceCarEntity" in schema_source
    assert "ReferenceTrackEntity" in schema_source
    assert "_SCHEMA_DRIFT_ENTITY_TYPES" in schema_source
    assert "for entity_type in _SCHEMA_DRIFT_ENTITY_TYPES" in schema_source
    assert "PRAGMA table_info({_sqlite_identifier(table.name)})" in schema_source
    assert "PRAGMA table_info({_sqlite_identifier(table)})" in schema_source


def test_schema_drift_check_function_preserves_key_order(monkeypatch) -> None:
    monkeypatch.setattr(MODULE, _private_helper_name("_vocabulary", "_check_constraints_missing"), lambda _session: 1)
    monkeypatch.setattr(MODULE, _private_helper_name("_schema", "_column_drift"), lambda _session: 2)
    monkeypatch.setattr(MODULE, _private_helper_name("_schema", "_server_default_drift"), lambda _session: 3)
    monkeypatch.setattr(MODULE, _private_helper_name("_frozen", "_schema_sql_drift"), lambda _session: 4)

    checks = schema_drift_checks(object())

    assert [check.key for check in checks] == [
        "vocabulary_check_constraints_missing",
        "schema_column_drift",
        "schema_server_default_drift",
        "frozen_schema_sql_drift",
    ]
    assert [check.severity for check in checks] == ["error", "error", "error", "error"]
    assert [check.count for check in checks] == [1, 2, 3, 4]


def test_db_doctor_service_does_not_reexport_private_schema_helpers() -> None:
    service_source = (ROOT / "forza" / "application" / "db_doctor_service.py").read_text(encoding="utf-8")

    assert "from .db_doctor.schema_checks import schema_drift_checks" in service_source
    for helper in _PRIVATE_HELPERS:
        assert helper not in service_source
        assert hasattr(MODULE, helper)
