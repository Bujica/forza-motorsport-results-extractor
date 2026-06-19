from __future__ import annotations

from tests._db_doctor_service_helpers import *  # noqa: F403


def test_db_doctor_accepts_legacy_raw_artifact_rows_when_sql_evidence_exists(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    ids = _seed_valid_run(db_path)
    error_path = tmp_path / "error.png"
    error_path.write_bytes(b"error image")
    error_hash = file_hash(error_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            run = session.get(ExtractionRunEntity, ids["run_id"])
            run.total_inputs = 2
            run.to_process = 2
            run.processed = 2
            run.succeeded = 1
            run.failed = 1
            session.add(run)
            session.add(
                ModelArtifactEntity(
                    id="legacy-raw-response-artifact",
                    run_id=str(ids["run_id"]),
                    image_file_id=str(ids["image_file_id"]),
                    extraction_result_id=str(ids["result_id"]),
                    attempt_id=str(ids["attempt_id"]),
                    artifact_type="raw_response",
                    file_path=str(tmp_path / "missing-raw-response.json"),
                    sha256="0" * 64,
                    size_bytes=999,
                    is_canonical=True,
                )
            )
            error_image = ImageFileEntity(
                id="image-error",
                file_hash=error_hash,
                file_name=error_path.name,
                current_name=error_path.name,
                current_path=str(error_path),
            )
            session.add(error_image)
            session.flush()
            error_input = RunInputEntity(
                run_id=str(ids["run_id"]),
                image_file_id=error_image.id,
                input_order=1,
                input_path=str(error_path),
                file_name=error_path.name,
                extension=".png",
                file_hash=error_hash,
                decision="process",
            )
            session.add(error_input)
            session.flush()
            error_result = ExtractionResultEntity(
                id="result-error",
                run_id=str(ids["run_id"]),
                run_input_id=error_input.id,
                image_file_id=error_image.id,
                status="error",
                error_message="parse failed",
                prompt_snapshot_id=session.get(ExtractionResultEntity, ids["result_id"]).prompt_snapshot_id,
                attempt_count=1,
            )
            session.add(error_result)
            session.flush()
            error_attempt = ExtractionAttemptEntity(
                id="attempt-error",
                extraction_result_id=error_result.id,
                run_id=str(ids["run_id"]),
                image_file_id=error_image.id,
                runtime_snapshot_id="runtime-1",
                attempt_number=1,
                attempt_reason="initial",
                status="error",
                accepted=False,
                rejected_reason="parse_error",
                parse_error="bad json",
                error_code="parse_error",
                error_message="bad json",
                raw_response="not json",
                request_messages_json=[{"role": "user", "content": "[image redacted]"}],
                request_config_json={},
                request_image_format="png",
                request_image_mime_type="image/png",
                request_image_width=1920,
                request_image_height=1080,
                request_image_bytes=100,
            )
            error_attempt.request_hash = canonical_request_hash(
                request_messages_json=error_attempt.request_messages_json,
                request_config_json=error_attempt.request_config_json,
                prompt_snapshot_id=error_result.prompt_snapshot_id,
                model=error_attempt.model,
                source_file_hash=error_hash,
                request_image_format=error_attempt.request_image_format,
                request_image_mime_type=error_attempt.request_image_mime_type,
                request_image_width=error_attempt.request_image_width,
                request_image_height=error_attempt.request_image_height,
                request_image_bytes=error_attempt.request_image_bytes,
            )
            session.add(error_attempt)
            session.flush()
            session.add(
                ModelArtifactEntity(
                    id="legacy-failed-attempt-artifact",
                    run_id=str(ids["run_id"]),
                    image_file_id=error_image.id,
                    extraction_result_id=error_result.id,
                    attempt_id=error_attempt.id,
                    artifact_type="failed_attempt",
                    file_path=str(tmp_path / "missing-failed-attempt.json"),
                    sha256="1" * 64,
                    size_bytes=500,
                    is_canonical=False,
                )
            )
            session.commit()
    finally:
        engine.dispose()

    _report, checks = _report_by_key(db_path)

    assert checks["canonical_artifacts_invalid"].count == 0
    assert checks["model_artifacts_invalid"].count == 0
    assert checks["error_attempts_missing_sql_evidence"].count == 0

def test_db_doctor_still_rejects_missing_non_sql_backed_model_artifacts(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    ids = _seed_valid_run(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            session.add(
                ModelArtifactEntity(
                    id="missing-request-preview-artifact",
                    run_id=str(ids["run_id"]),
                    image_file_id=str(ids["image_file_id"]),
                    extraction_result_id=str(ids["result_id"]),
                    attempt_id=str(ids["attempt_id"]),
                    artifact_type="request_preview",
                    file_path=str(tmp_path / "missing-request-preview.json"),
                    sha256="2" * 64,
                    size_bytes=123,
                    is_canonical=False,
                )
            )
            session.commit()
    finally:
        engine.dispose()

    _report, checks = _report_by_key(db_path)

    assert checks["canonical_artifacts_invalid"].count == 0
    assert checks["model_artifacts_invalid"].count == 1

def test_db_doctor_validates_noncanonical_model_artifacts(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    ids = _seed_valid_run(db_path)
    artifact_path = tmp_path / "request-preview.json"
    artifact_path.write_text("actual content", encoding="utf-8")
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            session.add(
                ModelArtifactEntity(
                    id="artifact-1",
                    run_id=str(ids["run_id"]),
                    image_file_id=str(ids["image_file_id"]),
                    extraction_result_id=str(ids["result_id"]),
                    attempt_id=str(ids["attempt_id"]),
                    artifact_type="request_preview",
                    file_path=str(artifact_path),
                    sha256="0" * 64,
                    size_bytes=1,
                    is_canonical=False,
                )
            )
            session.commit()
    finally:
        engine.dispose()

    _report, checks = _report_by_key(db_path)

    assert checks["canonical_artifacts_invalid"].count == 0
    assert checks["model_artifacts_invalid"].count == 1
