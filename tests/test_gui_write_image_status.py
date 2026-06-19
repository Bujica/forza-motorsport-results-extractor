from __future__ import annotations

from tests._gui_write_helpers import *  # noqa: F401,F403
from forza.db.models import ExtractionResultEntity, ExtractionRunEntity, ReviewCorrectionEntity, RunInputEntity

def test_gui_write_service_updates_image_state_and_emits_events(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    image_id, _, _, _ = _seed(db_path, image_path)
    events: list[PipelineEvent] = []

    service = GuiWriteService(db_path, event_sink=events.append)

    missing = service.set_file_status(image_id, "missing")
    assert missing is not None
    assert missing.file_status == "missing"

    visible = GuiReadService(db_path).get_image(image_id)
    assert visible is not None
    assert visible.best_lap_status == "pending"
    assert visible.file_status == "missing"

    assert [event.type for event in events] == [
        "image_status_changed",
    ]

def test_gui_write_service_validates_status_values(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    image_id, _, _, _ = _seed(db_path, image_path)

    service = GuiWriteService(db_path)

    with pytest.raises(ValueError):
        service.set_file_status(image_id, "archived")
    with pytest.raises(ValueError):
        service.set_file_status(image_id, "deleted")
    assert not hasattr(service, "set_best_lap_status")
    assert not hasattr(service, "exclude_from_best_laps")
    assert not hasattr(service, "reset_best_lap_status")

def test_gui_write_service_deletes_image_asset_database_records(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    image_id, flag_id, case_id, lap_id = _seed(db_path, image_path)
    events: list[PipelineEvent] = []

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            duplicate = ImageFileRepository(session).upsert(
                image_id="img-duplicate",
                file_hash="hash-1",
                file_name="copy.png",
                current_name="copy.png",
                current_path=tmp_path / "copy.png",
            )
            duplicate.duplicate_of_image_file_id = image_id
            session.add(
                ReviewCorrectionEntity(
                    id="correction-1",
                    stable_key="correction-1",
                    image_file_id=image_id,
                    lap_index=0,
                    field="track",
                    model_value="Wrong",
                    corrected_value="Mugello Circuit Full Circuit",
                    cause="review",
                    review_case_id=case_id,
                )
            )
            session.commit()
    finally:
        engine.dispose()

    service = GuiWriteService(db_path, event_sink=events.append)

    assert service.delete_image_file(image_id) is True

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            assert session.get(ImageFileEntity, image_id) is None
            assert session.get(ImageFlagEntity, flag_id) is None
            assert session.get(ReviewCaseEntity, case_id) is None
            assert session.get(ReviewCorrectionEntity, "correction-1") is None
            assert session.get(LapRecordEntity, lap_id) is None
            assert session.exec(select(ExtractionResultEntity)).all() == []
            assert session.exec(select(RunInputEntity).where(RunInputEntity.image_file_id == image_id)).all() == []
            run = session.get(ExtractionRunEntity, "run-1")
            assert run is not None
            assert run.total_inputs == 0
            assert run.to_process == 0
            assert run.processed == 0
            assert run.succeeded == 0
            assert run.failed == 0
            assert run.review_case_count == 0
            persisted_duplicate = session.get(ImageFileEntity, "img-duplicate")
            assert persisted_duplicate is not None
            assert persisted_duplicate.duplicate_of_image_file_id is None
    finally:
        engine.dispose()

    assert events[-1].type == "image_status_changed"
    assert events[-1].data["deleted"] is True

def test_gui_write_service_delete_canonical_duplicate_promotes_remaining_group(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    image_id, _, _, _ = _seed(db_path, image_path)
    copy_a = tmp_path / "copy-a.png"
    copy_b = tmp_path / "copy-b.png"
    copy_a.write_text("image", encoding="utf-8")
    copy_b.write_text("image", encoding="utf-8")

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            repo = ImageFileRepository(session)
            flags = ImageFlagRepository(session)
            duplicate_a = repo.upsert(
                image_id="img-duplicate-a",
                file_hash="hash-1",
                file_name=copy_a.name,
                current_name=copy_a.name,
                current_path=copy_a,
            )
            duplicate_a.duplicate_of_image_file_id = image_id
            duplicate_b = repo.upsert(
                image_id="img-duplicate-b",
                file_hash="hash-1",
                file_name=copy_b.name,
                current_name=copy_b.name,
                current_path=copy_b,
            )
            duplicate_b.duplicate_of_image_file_id = image_id
            flags.add_flag(
                image_file_id=duplicate_a.id,
                flag="duplicate",
                reason="duplicate_file_hash",
            )
            flags.add_flag(
                image_file_id=duplicate_b.id,
                flag="duplicate",
                reason="duplicate_file_hash",
            )
            session.add(duplicate_a)
            session.add(duplicate_b)
            session.commit()
    finally:
        engine.dispose()

    service = GuiWriteService(db_path)

    assert service.delete_image_file(image_id) is True

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            promoted = session.get(ImageFileEntity, "img-duplicate-a")
            remaining_duplicate = session.get(ImageFileEntity, "img-duplicate-b")
            assert promoted is not None
            assert remaining_duplicate is not None
            assert promoted.duplicate_of_image_file_id is None
            assert remaining_duplicate.duplicate_of_image_file_id == promoted.id

            duplicate_flags = session.exec(
                select(ImageFlagEntity).where(ImageFlagEntity.flag_type == "duplicate")
            ).all()
            active_flags = {
                flag.image_file_id
                for flag in duplicate_flags
                if flag.status == "active"
            }
            resolved_flags = {
                flag.image_file_id
                for flag in duplicate_flags
                if flag.status == "resolved"
            }
            assert promoted.id in resolved_flags
            assert promoted.id not in active_flags
            assert remaining_duplicate.id in active_flags
    finally:
        engine.dispose()


def test_gui_write_service_delete_last_duplicate_resolves_duplicate_flag(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    image_id, _, _, _ = _seed(db_path, image_path)
    copy_path = tmp_path / "copy.png"
    copy_path.write_text("image", encoding="utf-8")

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            repo = ImageFileRepository(session)
            duplicate = repo.upsert(
                image_id="img-duplicate",
                file_hash="hash-1",
                file_name=copy_path.name,
                current_name=copy_path.name,
                current_path=copy_path,
            )
            duplicate.duplicate_of_image_file_id = image_id
            ImageFlagRepository(session).add_flag(
                image_file_id=duplicate.id,
                flag="duplicate",
                reason="duplicate_file_hash",
            )
            session.add(duplicate)
            session.commit()
    finally:
        engine.dispose()

    service = GuiWriteService(db_path)

    assert service.delete_image_file(image_id) is True

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            duplicate = session.get(ImageFileEntity, "img-duplicate")
            assert duplicate is not None
            assert duplicate.duplicate_of_image_file_id is None
            assert (
                session.exec(
                    select(ImageFlagEntity).where(
                        ImageFlagEntity.image_file_id == duplicate.id,
                        ImageFlagEntity.flag_type == "duplicate",
                        ImageFlagEntity.status == "active",
                    )
                ).first()
                is None
            )
            resolved = session.exec(
                select(ImageFlagEntity).where(
                    ImageFlagEntity.image_file_id == duplicate.id,
                    ImageFlagEntity.flag_type == "duplicate",
                    ImageFlagEntity.status == "resolved",
                )
            ).first()
            assert resolved is not None
    finally:
        engine.dispose()


def test_gui_write_service_rejects_invalid_review_status_and_syncs_system_flags(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    image_id, _, case_id, lap_id = _seed(db_path, image_path)

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            matching_flag = ImageFlagRepository(session).add_flag(
                image_file_id=image_id,
                run_id="run-1",
                lap_record_id=lap_id,
                flag="track",
                reason="track",
            )
            session.commit()
            matching_flag_id = matching_flag.id
    finally:
        engine.dispose()

    service = GuiWriteService(db_path)

    with pytest.raises(ValueError):
        service._set_review_case_status(case_id, "auto_resolved")

    resolved = service.resolve_review_case(case_id)
    assert resolved is not None
    assert resolved.status == "resolved"

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            persisted = session.get(ImageFlagEntity, matching_flag_id)
            assert persisted is not None
            assert persisted.status == "resolved"
    finally:
        engine.dispose()

    reopened = service.reopen_review_case(case_id)
    assert reopened is not None
    assert reopened.status == "open"

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            persisted = session.get(ImageFlagEntity, matching_flag_id)
            assert persisted is not None
            assert persisted.status == "active"
    finally:
        engine.dispose()

def test_gui_write_service_requires_existing_current_database(tmp_path):
    service = GuiWriteService(tmp_path / "missing.sqlite3")

    with pytest.raises(RuntimeError):
        service.set_file_status("missing", "missing")
