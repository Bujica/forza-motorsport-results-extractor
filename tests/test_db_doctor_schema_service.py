from __future__ import annotations

from tests._db_doctor_service_helpers import *  # noqa: F403


def test_db_doctor_detects_frozen_schema_index_drift(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP INDEX idx_attempts_one_accepted_per_result")
        connection.commit()

    _report, checks = _report_by_key(db_path)
    assert checks["frozen_schema_sql_drift"].count == 1

def test_db_doctor_expected_schema_glue_covers_post_baseline_migrations():
    versions_dir = Path("forza/db/migrations/versions")
    post_baseline = {
        path.stem
        for path in versions_dir.glob("*.py")
        if path.stem != "0001_db_vnext_baseline"
    }

    assert set(_EXPECTED_SCHEMA_MIGRATION_REVISIONS) == post_baseline

def test_db_doctor_detects_frozen_schema_extra_view_drift(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE VIEW unexpected_debug_view AS SELECT 1 AS value")
        connection.commit()

    _report, checks = _report_by_key(db_path)
    assert checks["frozen_schema_sql_drift"].count == 1
