from __future__ import annotations

from tests._gui_write_helpers import *  # noqa: F401,F403

def test_gui_write_service_review_decision_updates_lap_record(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    image_id, _, case_id, lap_id = _seed(db_path, image_path)
    events: list[PipelineEvent] = []

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            case = session.get(ReviewCaseEntity, case_id)
            assert case is not None
            case.reason = "dirty_lap"
            image = session.get(ImageFileEntity, image_id)
            assert image is not None
            image.best_lap_status = "contributing"
            session.add(image)
            session.add(case)
            ImageFlagRepository(session).add_flag(
                image_file_id=image_id,
                run_id="run-1",
                extraction_result_id="result-1",
                lap_record_id=lap_id,
                flag="dirty_lap",
                reason="dirty_lap",
            )
            session.commit()
    finally:
        engine.dispose()

    service = GuiWriteService(db_path, event_sink=events.append)
    result = service.resolve_review_case_with_decision(
        case_id,
        lap_record_id=lap_id,
        decision={"field": "dirty", "value": "false"},
    )

    assert result is not None
    assert result.status == "resolved"
    assert result.resolution_note == "decision:dirty=false"

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            lap = session.get(LapRecordEntity, lap_id)
            assert lap is not None
            assert lap.dirty is False
            assert lap.is_best_lap is True
            image = ImageFileRepository(session).by_id(image_id)
            assert image is not None
            assert image.best_lap_status == "contributing"
            case = session.get(ReviewCaseEntity, case_id)
            assert case is not None
            assert case.outcome == "model_error"
            assert case.decision_field == "dirty"
            assert case.model_value == "true"
            assert case.corrected_value == "false"
            correction = session.exec(select(ReviewCorrectionEntity)).one()
            assert correction.image_file_id == image_id
            assert correction.lap_index == 0
            assert correction.field == "dirty"
            assert correction.model_value == "true"
            assert correction.corrected_value == "false"
            assert correction.review_case_id == case_id
            flag = session.exec(
                select(ImageFlagEntity).where(ImageFlagEntity.flag_type == "dirty_lap")
            ).one()
            assert flag.status == "resolved"
            assert flag.resolved_at is not None
    finally:
        engine.dispose()

    review_case = GuiReadService(db_path).list_review_queue(status="all")[0]
    assert review_case.model_value == "true"
    assert review_case.corrected_value == "false"
    assert review_case.current_best_lap == "01:00.000"
    assert review_case.current_dirty is False

    assert "lap_record_corrected" in [event.type for event in events]

def test_gui_write_service_rejects_ambiguous_dirty_decision(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    _, _, case_id, lap_id = _seed(db_path, image_path)

    service = GuiWriteService(db_path)
    with pytest.raises(ValueError, match="dirty decision must be boolean-like"):
        service.resolve_review_case_with_decision(
            case_id,
            lap_record_id=lap_id,
            decision={"field": "dirty", "value": "maybe"},
        )

def test_gui_write_service_review_decision_finds_unlinked_case_lap(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    image_id, _, case_id, lap_id = _seed(db_path, image_path)

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            case = session.get(ReviewCaseEntity, case_id)
            assert case is not None
            case.lap_record_id = None
            case.driver = "Bujica89"
            case.car = "Honda Civic"
            case.best_lap = "01:00.000"
            session.add(case)
            session.commit()
    finally:
        engine.dispose()

    service = GuiWriteService(db_path)
    result = service.resolve_review_case_with_decision(
        case_id,
        lap_record_id=None,
        decision={"field": "dirty", "value": False},
    )

    assert result is not None
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            lap = session.get(LapRecordEntity, lap_id)
            case = session.get(ReviewCaseEntity, case_id)
            assert lap is not None
            assert case is not None
            assert lap.dirty is False
            assert case.status == "resolved"
            assert case.lap_record_id == lap_id
    finally:
        engine.dispose()

def test_gui_write_service_review_decision_does_not_resolve_without_target_lap(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    _, _, case_id, _ = _seed(db_path, image_path)

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            case = session.get(ReviewCaseEntity, case_id)
            assert case is not None
            case.lap_record_id = None
            case.driver = "missing"
            case.car = "missing"
            case.best_lap = "09:99.999"
            session.add(case)
            session.commit()
    finally:
        engine.dispose()

    service = GuiWriteService(db_path)
    with pytest.raises(ReviewDecisionTargetNotFound):
        service.resolve_review_case_with_decision(
            case_id,
            lap_record_id=None,
            decision={"field": "dirty", "value": False},
        )

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            case = session.get(ReviewCaseEntity, case_id)
            assert case is not None
            assert case.status == "open"
            assert case.resolved_at is None
    finally:
        engine.dispose()

def test_dirty_review_decision_does_not_put_best_laps_in_pending(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    other_path = tmp_path / "other.png"
    image_path.write_text("image", encoding="utf-8")
    other_path.write_text("other", encoding="utf-8")
    image_id, _, case_id, lap_id = _seed(db_path, image_path)

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            image = session.get(ImageFileEntity, image_id)
            assert image is not None
            image.best_lap_status = "contributing"
            other = ImageFileRepository(session).upsert(
                image_id="img-2",
                file_hash="hash-2",
                file_name=other_path.name,
                current_name=other_path.name,
                current_path=other_path,
                best_lap_status="contributing",
            )
            session.flush()
            _add_lap_for_image(
                session,
                image_id=other.id,
                image_name=other.current_name,
                result_id="result-2",
                lap_id="lap-2",
                lap_index=0,
                best_lap="01:01.000",
                best_lap_ms=61000,
                driver="Bujica89",
            )
            session.commit()
    finally:
        engine.dispose()

    service = GuiWriteService(db_path)
    service.resolve_review_case_with_decision(
        case_id,
        lap_record_id=lap_id,
        decision={"field": "dirty", "value": False},
    )

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            changed_lap = session.get(LapRecordEntity, "lap-1")
            untouched_lap = session.get(LapRecordEntity, "lap-2")
            changed_image = session.get(ImageFileEntity, "img-1")
            untouched_image = session.get(ImageFileEntity, "img-2")
            assert changed_lap is not None
            assert untouched_lap is not None
            assert changed_image is not None
            assert untouched_image is not None
            assert changed_lap.is_best_lap is True
            assert changed_image.best_lap_status == "contributing"
            assert untouched_lap.is_best_lap is False
            assert untouched_image.best_lap_status == "non_contributing"
    finally:
        engine.dispose()

def test_dirty_review_decision_recomputes_pending_best_lap_status(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    image_id, _, case_id, lap_id = _seed(db_path, image_path)

    service = GuiWriteService(db_path, gamertag="Bujica89")
    service.resolve_review_case_with_decision(
        case_id,
        lap_record_id=lap_id,
        decision={"field": "dirty", "value": "false"},
    )

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            lap = session.get(LapRecordEntity, lap_id)
            image = session.get(ImageFileEntity, image_id)
            assert lap is not None
            assert image is not None
            assert lap.dirty is False
            assert lap.best_lap == "01:00.000"
            assert lap.is_best_lap is True
            assert image.best_lap_status == "contributing"
    finally:
        engine.dispose()
