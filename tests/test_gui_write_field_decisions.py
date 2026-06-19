from __future__ import annotations

from tests._gui_write_helpers import *  # noqa: F401,F403

def test_gui_write_service_track_decision_updates_all_laps_for_image_file(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    image_id, _, case_id, _ = _seed(db_path, image_path)

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            case = session.get(ReviewCaseEntity, case_id)
            assert case is not None
            case.reason = "track"
            case.trigger = "track_unresolved"
            case.lap_record_id = None
            case.driver = None
            case.car = None
            case.best_lap = None
            session.add(case)
            _add_lap_for_image(
                session,
                image_id=image_id,
                image_name=image_path.name,
                result_id="result-1",
                lap_id="lap-2",
                lap_index=1,
                best_lap="01:01.000",
                best_lap_ms=61000,
            )
            session.commit()
    finally:
        engine.dispose()

    service = GuiWriteService(db_path)
    result = service.resolve_review_case_with_decision(
        case_id,
        lap_record_id=None,
        decision={"field": "track", "value": "Silverstone Racing Circuit Grand Prix Circuit"},
    )

    assert result is not None
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            laps = session.exec(
                select(LapRecordEntity).where(LapRecordEntity.image_file_id == image_id)
            ).all()
            image = session.get(ImageFileEntity, image_id)
            assert {lap.track for lap in laps} == {"Silverstone Racing Circuit Grand Prix Circuit"}
            assert image is not None
            assert image.best_lap_status != "pending"
            case = session.get(ReviewCaseEntity, case_id)
            assert case is not None
            assert case.status == "resolved"
            assert case.lap_record_id in {lap.id for lap in laps}
    finally:
        engine.dispose()

def test_gui_write_service_weather_decision_normalizes_and_updates_all_laps(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    image_id, _, case_id, _ = _seed(db_path, image_path)

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            case = session.get(ReviewCaseEntity, case_id)
            assert case is not None
            case.reason = "weather"
            case.trigger = "weather_unknown"
            case.lap_record_id = None
            case.driver = None
            case.car = None
            case.best_lap = None
            session.add(case)
            _add_lap_for_image(
                session,
                image_id=image_id,
                image_name=image_path.name,
                result_id="result-1",
                lap_id="lap-2",
                lap_index=1,
                best_lap="01:01.000",
                best_lap_ms=61000,
            )
            session.commit()
    finally:
        engine.dispose()

    service = GuiWriteService(db_path)
    result = service.resolve_review_case_with_decision(
        case_id,
        lap_record_id=None,
        decision={"field": "weather", "value": "wet"},
    )

    assert result is not None
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            laps = session.exec(
                select(LapRecordEntity).where(LapRecordEntity.image_file_id == image_id)
            ).all()
            assert {lap.weather for lap in laps} == {"rain"}
            case = session.get(ReviewCaseEntity, case_id)
            assert case is not None
            assert case.status == "resolved"
    finally:
        engine.dispose()

def test_driver_name_decision_recomputes_best_laps_and_leaves_no_pending_clean_images(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    image_id, _, case_id, lap_id = _seed(db_path, image_path)

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            lap = session.get(LapRecordEntity, lap_id)
            case = session.get(ReviewCaseEntity, case_id)
            image = session.get(ImageFileEntity, image_id)
            assert lap is not None
            assert case is not None
            assert image is not None
            lap.dirty = False
            lap.driver = "42 Bujica89"
            lap.driver_normalized = "42 bujica89"
            lap.is_best_lap = False
            image.best_lap_status = "pending"
            case.reason = "driver_name"
            case.trigger = "numeric_prefix"
            case.driver = "42 Bujica89"
            case.driver_normalized = "42 bujica89"
            session.add(lap)
            session.add(image)
            session.add(case)
            session.commit()
    finally:
        engine.dispose()

    service = GuiWriteService(db_path, gamertag="Bujica89")
    service.resolve_review_case_with_decision(
        case_id,
        lap_record_id=lap_id,
        decision={"field": "driver", "value": "Bujica89"},
    )

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            image = session.get(ImageFileEntity, image_id)
            lap = session.get(LapRecordEntity, lap_id)
            assert image is not None
            assert lap is not None
            assert lap.driver == "Bujica89"
            assert image.best_lap_status == "contributing"
            assert lap.is_best_lap is True
    finally:
        engine.dispose()
