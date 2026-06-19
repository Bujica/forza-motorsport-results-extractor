from __future__ import annotations

from tests._db_doctor_service_helpers import *  # noqa: F403


def test_db_doctor_validates_available_image_path_and_content_identity(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    ids = _seed_valid_run(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            image = session.get(ImageFileEntity, ids["image_file_id"])
            current_path = Path(image.current_path)
            session.add(
                ImageFileEntity(
                    id="image-conflict",
                    file_hash="other-hash",
                    file_name="other.png",
                    current_name="other.png",
                    current_path=image.current_path,
                )
            )
            session.commit()
    finally:
        engine.dispose()

    current_path.write_bytes(b"changed bytes")
    _report, checks = _report_by_key(db_path)
    assert checks["available_image_path_conflicts"].count == 1
    assert checks["available_images_hash_mismatch"].count == 2
    assert checks["available_images_missing_files"].count == 0

    current_path.unlink()
    _report, checks = _report_by_key(db_path)
    assert checks["available_images_missing_files"].count == 2

def test_db_doctor_reports_best_lap_rows_without_positive_milliseconds(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    ids = _seed_valid_run(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            session.add(
                LapRecordEntity(
                    id="lap-zero-best-ms",
                    run_id=str(ids["run_id"]),
                    image_file_id=str(ids["image_file_id"]),
                    extraction_result_id=str(ids["result_id"]),
                    lap_index=0,
                    source_file="raw.png",
                    driver="Driver",
                    driver_normalized="driver",
                    car="Car",
                    car_normalized="car",
                    race_class="A",
                    track="Track",
                    track_normalized="track",
                    weather="dry",
                    best_lap="1:23.456",
                    best_lap_ms=0,
                    dirty=False,
                    is_best_lap=True,
                )
            )
            session.commit()
    finally:
        engine.dispose()

    _report, checks = _report_by_key(db_path)
    assert checks["best_laps_without_positive_ms"].count == 1

def test_db_doctor_reports_pending_image_with_clean_laps(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    ids = _seed_valid_run(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            session.add(
                LapRecordEntity(
                    id="lap-clean-pending",
                    run_id=str(ids["run_id"]),
                    image_file_id=str(ids["image_file_id"]),
                    extraction_result_id=str(ids["result_id"]),
                    lap_index=0,
                    driver="Bujica89",
                    car="Car",
                    race_class="A",
                    track="Track",
                    weather="dry",
                    best_lap="1:00.000",
                    best_lap_ms=60000,
                    dirty=False,
                    is_best_lap=False,
                )
            )
            session.commit()
    finally:
        engine.dispose()

    _report, checks = _report_by_key(db_path)

    assert checks["best_lap_status_stale_pending"].count == 1
