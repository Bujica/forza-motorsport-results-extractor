from __future__ import annotations

from tests._db_doctor_service_helpers import *  # noqa: F403


def test_db_doctor_validates_semantic_parent_chains(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    ids = _seed_valid_run(db_path)
    other_path = tmp_path / "other.png"
    other_path.write_bytes(b"other image")
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            other = ImageFileEntity(
                id="image-other",
                file_hash=file_hash(other_path),
                file_name=other_path.name,
                current_name=other_path.name,
                current_path=str(other_path),
            )
            session.add(other)
            session.flush()
            run_input = session.get(RunInputEntity, ids["run_input_id"])
            run_input.image_file_id = other.id
            session.add(run_input)
            lap = LapRecordEntity(
                id="lap-parent-mismatch",
                run_id=str(ids["run_id"]),
                image_file_id=other.id,
                extraction_result_id=str(ids["result_id"]),
                lap_index=0,
                best_lap_ms=60000,
            )
            session.add(lap)
            session.add(
                ModelArtifactEntity(
                    id="artifact-parent-mismatch",
                    run_id=str(ids["run_id"]),
                    image_file_id=other.id,
                    extraction_result_id=str(ids["result_id"]),
                    attempt_id=str(ids["attempt_id"]),
                    artifact_type="request_preview",
                    file_path=str(tmp_path / "missing-artifact.json"),
                    sha256="0" * 64,
                    size_bytes=0,
                )
            )
            session.add(
                ReviewCaseEntity(
                    id="review-parent-mismatch",
                    run_id=str(ids["run_id"]),
                    image_file_id=other.id,
                    extraction_result_id=str(ids["result_id"]),
                    reason="dirty_lap",
                    business_key="review-parent-mismatch",
                )
            )
            session.add(
                ImageFlagEntity(
                    id="flag-parent-mismatch",
                    run_id=str(ids["run_id"]),
                    image_file_id=other.id,
                    extraction_result_id=str(ids["result_id"]),
                    flag_key="flag-parent-mismatch",
                    flag_type="dirty_lap",
                )
            )
            session.commit()
    finally:
        engine.dispose()

    _report, checks = _report_by_key(db_path)
    assert checks["result_input_parent_mismatch"].count == 1
    assert checks["model_artifact_parent_mismatch"].count == 1
    assert checks["lap_parent_mismatch"].count == 1
    assert checks["review_parent_mismatch"].count == 1
    assert checks["flag_parent_mismatch"].count == 1

def test_db_doctor_reports_volatile_review_business_key(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    ids = _seed_valid_run(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            lap = LapRecordEntity(
                id="lap-1",
                run_id=str(ids["run_id"]),
                image_file_id=str(ids["image_file_id"]),
                extraction_result_id=str(ids["result_id"]),
                lap_index=0,
                driver="Driver",
                driver_normalized="driver",
                car="Car",
                car_normalized="car",
                race_class="A",
                track="Track",
                track_normalized="track",
                best_lap="1:00.000",
                best_lap_ms=60000,
            )
            session.add(lap)
            session.flush()
            session.add(
                ReviewCaseEntity(
                    id="review-1",
                    run_id=str(ids["run_id"]),
                    image_file_id=str(ids["image_file_id"]),
                    extraction_result_id=str(ids["result_id"]),
                    lap_record_id=lap.id,
                    reason="dirty_lap",
                    business_key=f"dirty_lap:{lap.id}",
                )
            )
            session.commit()
    finally:
        engine.dispose()

    _report, checks = _report_by_key(db_path)

    assert checks["review_business_key_uses_lap_record_id"].count == 1

def test_db_doctor_reports_noncanonical_review_key(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    ids = _seed_valid_run(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            session.add(
                ReviewCaseEntity(
                    id="legacy-noncanonical",
                    case_number=1,
                    image_file_id=str(ids["image_file_id"]),
                    status="resolved",
                    reason="dirty_lap",
                    outcome="model_error",
                    decision_field="dirty",
                    corrected_value="false",
                    driver="Driver",
                    driver_normalized="driver",
                    car="Car",
                    car_normalized="car",
                    best_lap="1:00.000",
                    lap_index=0,
                    business_key=f"dirty_lap:{ids['image_file_id']}:0:driver",
                    resolution_note="decision:dirty=false",
                )
            )
            session.commit()
    finally:
        engine.dispose()

    _report, checks = _report_by_key(db_path)

    assert checks["review_business_key_not_canonical"].count == 1
