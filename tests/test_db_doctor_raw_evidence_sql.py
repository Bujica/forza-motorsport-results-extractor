from __future__ import annotations

from pathlib import Path

from tests._db_doctor_service_helpers import *  # noqa: F403


ROOT = Path(__file__).resolve().parents[1]


def test_accepted_attempt_raw_evidence_check_uses_one_sql_query() -> None:
    source = (ROOT / "forza" / "application" / "db_doctor" / "artifact_checks.py").read_text(encoding="utf-8")
    body = source.split("def _accepted_attempts_missing_raw_evidence", 1)[1].split(
        "\ndef _invalid_canonical_artifacts",
        1,
    )[0]

    assert "NOT EXISTS" in body
    assert "model_artifacts" in body
    assert "artifact_type = 'raw_response'" in body
    assert "is_canonical = 1" in body
    assert "for attempt_id" not in body
    assert "return _scalar_sql(" in body


def test_db_doctor_reports_missing_raw_evidence_for_accepted_attempt_without_sql_or_artifact(
    migrated_db_path: Path,
) -> None:
    db_path = migrated_db_path
    ids = _seed_valid_run(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            attempt = session.get(ExtractionAttemptEntity, ids["attempt_id"])
            attempt.raw_response = None
            session.add(attempt)
            session.commit()
    finally:
        engine.dispose()

    _report, checks = _report_by_key(db_path)

    assert checks["accepted_attempts_missing_raw_evidence"].count == 1


def test_db_doctor_accepts_canonical_raw_artifact_as_accepted_attempt_evidence(
    tmp_path: Path,
    migrated_db_path: Path,
) -> None:
    db_path = migrated_db_path
    ids = _seed_valid_run(db_path)
    artifact_path = tmp_path / "raw-response.json"
    artifact_bytes = b'{"ok": true}'
    artifact_path.write_bytes(artifact_bytes)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            attempt = session.get(ExtractionAttemptEntity, ids["attempt_id"])
            attempt.raw_response = None
            session.add(attempt)
            session.add(
                ModelArtifactEntity(
                    id="canonical-raw-response-artifact",
                    run_id=str(ids["run_id"]),
                    image_file_id=str(ids["image_file_id"]),
                    extraction_result_id=str(ids["result_id"]),
                    attempt_id=str(ids["attempt_id"]),
                    artifact_type="raw_response",
                    file_path=str(artifact_path),
                    sha256=__import__("hashlib").sha256(artifact_bytes).hexdigest(),
                    size_bytes=len(artifact_bytes),
                    is_canonical=True,
                )
            )
            session.commit()
    finally:
        engine.dispose()

    _report, checks = _report_by_key(db_path)

    assert checks["accepted_attempts_missing_raw_evidence"].count == 0
    assert checks["canonical_artifacts_invalid"].count == 0
