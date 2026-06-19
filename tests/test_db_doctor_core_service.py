from __future__ import annotations

from tests._db_doctor_service_helpers import *  # noqa: F403


def test_db_doctor_accepts_valid_vnext_run(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    _seed_valid_run(db_path)

    report, checks = _report_by_key(db_path)

    assert report.ok
    assert checks["sqlite_integrity_check"].count == 0
    assert checks["foreign_key_violations"].count == 0
    assert checks["ok_results_without_accepted_attempt"].count == 0
    assert checks["run_inputs_process_without_one_result"].count == 0
    assert checks["accepted_attempts_missing_raw_evidence"].count == 0

def test_db_doctor_reports_foreign_key_violations(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            """
            INSERT INTO run_inputs (run_id, input_order, input_path, decision, created_at)
            VALUES ('missing-run', 0, 'missing.png', 'skip', '2026-06-04T00:00:00Z')
            """
        )
        connection.commit()

    _report, checks = _report_by_key(db_path)

    assert checks["foreign_key_violations"].count == 1

def test_db_doctor_does_not_create_runtime_wal_sidecars(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    wal = Path(f"{db_path}-wal")
    shm = Path(f"{db_path}-shm")

    report = DbDoctorService().run(db_path)

    assert report.ok
    assert not wal.exists()
    assert not shm.exists()

def test_db_doctor_validates_source_review_and_flag_status_vocabularies(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    ids = _seed_valid_run(db_path)
    created_at = "2026-06-09 00:00:00"

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            """
            UPDATE image_files
            SET file_status = 'unknown',
                best_lap_status = 'winner'
            WHERE id = ?
            """,
            (ids["image_file_id"],),
        )
        connection.execute(
            """
            INSERT INTO review_cases (
                id, image_file_id, status, reason,
                business_key, created_at
            )
            VALUES (
                'review-invalid-status', ?, 'pending', 'dirty_lap',
                'invalid-review-status', ?
            )
            """,
            (ids["image_file_id"], created_at),
        )
        connection.execute(
            """
            INSERT INTO image_flags (
                id, image_file_id, flag_key, flag_scope, flag_type,
                status, created_by, created_at
            )
            VALUES (
                'flag-invalid-status', ?, 'invalid-flag-status', 'result',
                'dirty_lap', 'open', 'system', ?
            )
            """,
            (ids["image_file_id"], created_at),
        )
        connection.execute("PRAGMA ignore_check_constraints = OFF")
        connection.commit()

    _report, checks = _report_by_key(db_path)
    assert checks["invalid_status_values"].count == 3
