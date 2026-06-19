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

def test_list_best_laps_is_read_only_when_frontier_is_empty(tmp_path):
    engine = make_engine(tmp_path)
    result = make_result()

    with Session(engine) as session:
        image = ImageFileRepository(session).upsert(
            file_hash=result.file_hash,
            file_name="input.png",
            current_name=result.source_file,
        )
        run = RunRepository(session).create(run_id="run-readonly-best", backend="lmstudio", model="qwen")
        LapRepository(session).add_result(result, run_id=run.id, image_file_id=image.id)
        session.commit()

        rows = LapRepository(session).list_best_laps(run_id=run.id)
        laps = LapRepository(session).list_by_run(run.id)
        image = ImageFileRepository(session).by_id(image.id)

    assert rows == []
    assert all(lap.is_best_lap is False for lap in laps)
    assert image.best_lap_status == "pending"

def test_lap_record_idempotency_uses_lap_index_not_driver_car_time(tmp_path):
    engine = make_engine(tmp_path)
    result = make_result()
    # Deliberately duplicate the first lap contents as a second visible row.
    result.session.entries[1] = result.session.entries[0]
    with Session(engine) as session:
        image = ImageFileRepository(session).upsert(file_hash="h", file_name="raw.png")
        run = RunRepository(session).create(run_id="run-laps", backend="lmstudio", model="qwen")
        entities = LapRepository(session).add_result(result, run_id=run.id, image_file_id=image.id)
        session.commit()

        assert len(entities) == 2
        rows = LapRepository(session).list_by_run("run-laps")
        assert [row.lap_index for row in rows] == [0, 1]

        entities_again = LapRepository(session).add_result(result, run_id=run.id, image_file_id=image.id)
        session.commit()
        assert entities_again == []
        assert len(LapRepository(session).list_by_run("run-laps")) == 2

def test_relational_clean_uses_player_frontier_not_simple_best(tmp_path):
    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    slow = _rel_result(
        "slow.png",
        "h_slow",
        [_rel_entry(REL_GAMERTAG, best_lap="1:35.000", best_lap_ms=95000)],
    )
    fast = _rel_result(
        "fast.png",
        "h_fast",
        [_rel_entry(REL_GAMERTAG, best_lap="1:30.000", best_lap_ms=90000)],
    )

    _seed_runtime_results(db, "clean-run", [slow, fast])
    db.recompute_best_laps(run_id="clean-run", gamertag=REL_GAMERTAG)
    clean = db.list_clean_flat(run_id="clean-run")

    assert [result.source_file for result in clean] == ["fast.png"]
    assert clean[0].best_lap_ms == 90000
    db.close()

def test_relational_clean_keeps_only_opponents_faster_than_player(tmp_path):
    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    result = _rel_result(
        "race.png",
        "h_race",
        [
            _rel_entry(REL_GAMERTAG, best_lap="1:30.000", best_lap_ms=90000),
            _rel_entry("Fast Opponent", best_lap="1:28.000", best_lap_ms=88000),
            _rel_entry("Slow Opponent", best_lap="1:35.000", best_lap_ms=95000),
        ],
    )

    _seed_runtime_results(db, "opponent-run", [result])
    db.recompute_best_laps(run_id="opponent-run", gamertag=REL_GAMERTAG)
    clean = db.list_clean_flat(run_id="opponent-run")

    assert len(clean) == 2
    drivers = {entry.driver for entry in clean}
    assert drivers == {REL_GAMERTAG, "Fast Opponent"}
    db.close()

def test_relational_clean_updates_image_file_best_lap_status(tmp_path):
    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    slow = _rel_result(
        "slow.png",
        "h_slow_status",
        [_rel_entry(REL_GAMERTAG, best_lap="1:35.000", best_lap_ms=95000)],
    )
    fast = _rel_result(
        "fast.png",
        "h_fast_status",
        [_rel_entry(REL_GAMERTAG, best_lap="1:30.000", best_lap_ms=90000)],
    )

    _seed_runtime_results(db, "status-run", [slow, fast])
    db.recompute_best_laps(run_id="status-run", gamertag=REL_GAMERTAG)
    db.list_clean_flat(run_id="status-run")

    with Session(db._engine_for_db()) as session:
        images = ImageFileRepository(session)
        assert images.by_hash("h_fast_status").best_lap_status == "contributing"
        assert images.by_hash("h_slow_status").best_lap_status == "non_contributing"
    db.close()
