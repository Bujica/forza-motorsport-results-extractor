from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from forza.application import DatabaseService
from forza.db import session_scope
from forza.db.models import (
    ExportArtifactEntity,
    ExternalRecordImportEntity,
    ExtractionAttemptEntity,
    ExtractionRunEntity,
    ImageFlagEntity,
    LapRecordEntity,
    ModelArtifactEntity,
    ModelRuntimeSnapshotEntity,
    PromptSnapshotEntity,
    ReferenceCarEntity,
    ReferenceTrackEntity,
    ReviewCaseEntity,
    ReviewCorrectionEntity,
    RunInputEntity,
    ImageFileEntity,
)
from forza.db.repositories import (
    ExportArtifactRepository,
    ExternalRecordRepository,
    ExtractionResultRepository,
    LapRepository,
    ReviewRepository,
    RunRepository,
    ImageFileRepository,
)
from forza.schemas import (
    BestLapStatus,
    ExternalLapRecord,
    ExtractionResult,
    ImageMetadata,
    LapRecord,
    ModelExtractionAttempt,
    ModelResponseStats,
    RaceClass,
    RaceSession,
    ReviewCase,
    ReviewDecisionField,
    ReviewOutcome,
    ReviewReason,
    ReviewTrigger,
    ImageFile,
    ImageFileStatus,
    WeatherType,
    dump_schema,
)
from pydantic import ValidationError

from tests._db_repository_helpers import (
    REL_GAMERTAG,
    REL_TRACK,
    _rel_entry,
    _rel_result,
    _seed_runtime_results,
    make_engine,
    make_result,
)

def test_image_file_upsert_keeps_same_hash_files_as_distinct_physical_rows(tmp_path):
    engine = make_engine(tmp_path)

    with Session(engine) as session:
        repo = ImageFileRepository(session)
        first = repo.upsert(
            file_hash="same",
            file_name="old.png",
            current_path=tmp_path / "old.png",
        )
        session.commit()

        second = repo.upsert(
            file_hash="same",
            file_name="new.png",
            current_name="Track - D #1.png",
            current_path=tmp_path / "new.png",
        )
        session.commit()

        rows = session.exec(select(ImageFileEntity).order_by(ImageFileEntity.current_name)).all()
        assert len(rows) == 2
        assert second.id != first.id
        assert repo.by_hash("same").id == first.id
        assert [row.file_hash for row in rows] == ["same", "same"]
        assert second.current_name == "Track - D #1.png"

def test_image_file_upsert_does_not_replace_identity_at_reused_path(tmp_path):
    engine = make_engine(tmp_path)
    path = tmp_path / "same-name.png"
    path.write_bytes(b"first")

    with Session(engine) as session:
        repo = ImageFileRepository(session)
        first = repo.upsert(file_hash="hash-first", file_name=path.name, current_path=path)
        session.commit()

        path.write_bytes(b"second")
        second = repo.upsert(file_hash="hash-second", file_name=path.name, current_path=path)
        session.commit()

        rows = session.exec(select(ImageFileEntity).order_by(ImageFileEntity.created_at)).all()
        assert len(rows) == 2
        assert first.id != second.id
        assert first.file_hash == "hash-first"
        assert first.file_status == "missing"
        assert second.file_hash == "hash-second"
        assert second.file_status == "available"

def test_image_file_upsert_updates_current_name(tmp_path):
    engine = make_engine(tmp_path)

    with Session(engine) as session:
        repo = ImageFileRepository(session)
        path = tmp_path / "original.png"
        repo.upsert(file_hash="h", file_name="original.png", current_path=path)
        session.commit()

        entity = repo.upsert(
            file_hash="h",
            file_name="should_be_ignored.png",
            semantic_name="Track - A #1.png",
            current_name="Track - A #1.png",
            current_path=path,
        )
        session.commit()

        assert entity.semantic_name == "Track - A #1.png"
        assert entity.current_name == "Track - A #1.png"

def test_register_duplicate_image_file_records_flag_without_moving_file(tmp_path):
    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    db.begin_run(
        run_id="run-1",
        backend="lmstudio",
        model="qwen",
        prompt_name="v1",
        input_dir=str(tmp_path),
    )

    original = tmp_path / "input" / "original.png"
    duplicate = tmp_path / "input" / "duplicate.png"
    original.parent.mkdir()
    original.write_bytes(b"same")
    duplicate.write_bytes(b"same")

    canonical_id = db.register_image_file(file_hash="same", path=original, run_id="run-1")
    duplicate_id = db.register_image_file(
        file_hash="same",
        path=duplicate,
        duplicate_of_hash="same",
        run_id="run-1",
    )

    with Session(db._engine_for_db()) as session:
        duplicate_row = session.get(ImageFileEntity, duplicate_id)
        flags = session.exec(
            select(ImageFlagEntity).where(ImageFlagEntity.image_file_id == duplicate_id)
        ).all()

    assert duplicate.exists()
    assert duplicate_id != canonical_id
    assert duplicate_row.duplicate_of_image_file_id == canonical_id
    assert (duplicate_row.image_metadata_json or {}).get("duplicate_of_image_file_id") is None
    assert duplicate_row.best_lap_status == "pending"
    assert [flag.flag_type for flag in flags] == ["duplicate"]
    db.close()

def test_image_file_tracks_current_paths(tmp_path):
    engine = make_engine(tmp_path)
    with Session(engine) as session:
        repo = ImageFileRepository(session)
        first = repo.upsert(
            file_hash="path-hash",
            file_name="raw.png",
            current_name="Track - A #1.png",
            current_path=tmp_path / "output" / "Track - A #1.png",
            semantic_name="Track - A #1.png",
        )
        session.commit()
        second = repo.upsert(
            file_hash="path-hash",
            file_name="ignored.png",
            current_name="Track - A #1 (2).png",
            current_path=tmp_path / "output" / "Track - A #1 (2).png",
            semantic_name="Track - A #1 (2).png",
        )
        session.commit()

        assert second.id != first.id
        assert Path(first.current_path).parts[-2:] == ("output", "Track - A #1.png")
        assert second.current_name == "Track - A #1 (2).png"
        assert Path(second.current_path).parts[-2:] == ("output", "Track - A #1 (2).png")

def test_image_file_promoted_metadata_fields_use_columns(tmp_path):
    engine = make_engine(tmp_path)
    modified_at = datetime(2026, 6, 9, 12, 30, tzinfo=timezone.utc)
    persisted_modified_at = modified_at.replace(tzinfo=None)

    with Session(engine) as session:
        original = ImageFileRepository(session).upsert(
            file_hash="source-original",
            file_name="original.png",
            path=tmp_path / "original.png",
        )
        duplicate = ImageFileRepository(session).upsert(
            file_hash="source-duplicate",
            file_name="duplicate.png",
            path=tmp_path / "duplicate.png",
            duplicate_of_image_file_id=original.id,
            metadata=ImageMetadata(
                file_size_bytes=123,
                file_modified_at=modified_at,
                image_metadata_json={
                    "file_modified_at": "legacy-json-value",
                    "duplicate_of_image_file_id": "legacy-json-duplicate",
                    "camera": "capture-card",
                },
            ),
        )
        session.commit()

        schema = ImageFileRepository(session).to_schema(duplicate)
        original_id = original.id
        duplicate_of_image_file_id = duplicate.duplicate_of_image_file_id
        file_modified_at = duplicate.file_modified_at
        image_metadata_json = dict(duplicate.image_metadata_json or {})

    assert duplicate_of_image_file_id == original_id
    assert file_modified_at == persisted_modified_at
    assert image_metadata_json == {"camera": "capture-card"}
    assert schema.duplicate_of_image_file_id == original_id
    assert schema.file_modified_at == persisted_modified_at
