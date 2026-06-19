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

def test_review_case_number_uses_sql_column(tmp_path):
    engine = make_engine(tmp_path)

    with Session(engine) as session:
        session.add(
            ReviewCaseEntity(
                id="existing-review",
                reason="dirty_lap",
                business_key="dirty_lap:existing",
                case_number=41,
            )
        )
        repo = ReviewRepository(session)

        inserted, _kept, _removed = repo.upsert_review_cases([
            ReviewCase(
                reason="track",
                source_file="new.png",
                track="Unknown",
                race_class="A",
                weather="dry",
                temp_f=None,
                driver=None,
                car=None,
                best_lap=None,
            )
        ])
        session.commit()

        rows = session.exec(select(ReviewCaseEntity).where(ReviewCaseEntity.id != "existing-review")).all()

    assert inserted == 1
    assert rows[0].case_number == 42
    assert rows[0].source_file == "new.png"
    assert rows[0].weather == "dry"
    assert rows[0].temp_f is None

def test_review_candidates_use_six_canonical_reasons_with_triggers(tmp_path):
    engine = make_engine(tmp_path)
    result = ExtractionResult(
        "review.png",
        "review-hash",
        RaceSession(
            "Unknown (ambiguous layout): Mugello Circuit",
            None,
            None,
            [
                LapRecord(
                    "250 CyanoticBoot9",
                    "Unlisted Car",
                    "Unknown",
                    "01:00.000▲",
                    60000,
                    True,
                )
            ],
            "Unknown",
            "unknown",
        ),
        "ok",
    )
    with Session(engine) as session:
        session.add(ReferenceTrackEntity(id="track-1", name="Mugello Circuit Full Circuit"))
        session.add(ReferenceCarEntity(id="car-1", name="Known Car"))
        image = ImageFileRepository(session).upsert(file_hash=result.file_hash, file_name="review.png")
        run = RunRepository(session).create(run_id="run-review", backend="lmstudio", model="qwen")
        LapRepository(session).add_result(result, run_id=run.id, image_file_id=image.id)
        session.flush()
        lap = session.exec(select(LapRecordEntity)).one()
        lap.is_best_lap = True
        session.add(lap)
        session.commit()

        cases = LapRepository(session).query_review_candidates()

    assert {case.reason for case in cases} == {
        "dirty_lap",
        "track",
        "weather",
        "race_class",
        "car",
        "driver_name",
    }
    assert {case.trigger for case in cases} >= {
        "model_marked_dirty",
        "track_unresolved",
        "weather_unknown",
        "class_unknown",
        "car_not_in_reference",
        "numeric_prefix",
    }

def test_numeric_prefix_review_trigger_accepts_two_digit_prefix(tmp_path):
    engine = make_engine(tmp_path)
    result = ExtractionResult(
        "numeric-prefix.png",
        "numeric-prefix-hash",
        RaceSession(
            REL_TRACK,
            None,
            None,
            [_rel_entry("42 LionZera7559")],
            "A",
            "dry",
        ),
        "ok",
    )
    with Session(engine) as session:
        image = ImageFileRepository(session).upsert(file_hash=result.file_hash, file_name=result.source_file)
        run = RunRepository(session).create(run_id="run-two-digit-prefix", backend="lmstudio", model="qwen")
        LapRepository(session).add_result(result, run_id=run.id, image_file_id=image.id)
        session.commit()

        cases = LapRepository(session).query_review_candidates()

    assert [case.trigger for case in cases if case.reason == "driver_name"] == ["numeric_prefix"]

def test_review_upsert_uses_only_canonical_dirty_business_key(tmp_path):
    engine = make_engine(tmp_path)
    with Session(engine) as session:
        image = ImageFileRepository(session).upsert(file_hash="legacy-hash", file_name="legacy.png")
        image_id = image.id
        session.flush()
        session.add(
            ReviewCaseEntity(
                id="legacy-resolved",
                image_file_id=image.id,
                status="resolved",
                reason="dirty_lap",
                outcome="model_error",
                decision_field="dirty",
                model_value="true",
                corrected_value="false",
                driver="Driver",
                driver_normalized="driver",
                car="Car",
                car_normalized="car",
                best_lap="1:00.000",
                lap_index=0,
                business_key=f"dirty_lap:{image.id}:0:driver",
            )
        )
        session.commit()

        inserted, kept, removed = ReviewRepository(session).upsert_review_cases([
            ReviewCase(
                reason="dirty_lap",
                source_file="legacy.png",
                track=REL_TRACK,
                race_class="A",
                weather="dry",
                temp_f=None,
                driver="Driver",
                car="Car",
                best_lap="1:00.000",
                image_file_id=image.id,
                lap_index=0,
                trigger="model_marked_dirty",
                model_value="true",
            )
        ])
        session.commit()

        open_cases = session.exec(select(ReviewCaseEntity).where(ReviewCaseEntity.status == "open")).all()

    assert (inserted, kept, removed) == (1, 0, 0)
    assert [case.business_key for case in open_cases] == [f"dirty_lap:{image_id}:0"]

def test_review_upsert_deduplicates_duplicate_canonical_candidates(tmp_path):
    engine = make_engine(tmp_path)
    with Session(engine) as session:
        image = ImageFileRepository(session).upsert(file_hash="duplicate-candidate-hash", file_name="duplicate.png")
        session.flush()
        candidate = ReviewCase(
            reason="dirty_lap",
            source_file="duplicate.png",
            track=REL_TRACK,
            race_class="A",
            weather="dry",
            temp_f=None,
            driver="Driver",
            car="Car",
            best_lap="1:00.000",
            image_file_id=image.id,
            lap_index=0,
            trigger="model_marked_dirty",
            model_value="true",
        )

        inserted, kept, removed = ReviewRepository(session).upsert_review_cases([candidate, candidate])
        session.commit()

        rows = session.exec(select(ReviewCaseEntity)).all()

    assert (inserted, kept, removed) == (1, 0, 0)
    assert len(rows) == 1

def test_review_upsert_does_not_use_semantic_dirty_key_as_runtime_identity(tmp_path):
    engine = make_engine(tmp_path)
    with Session(engine) as session:
        image = ImageFileRepository(session).upsert(file_hash="semantic-hash", file_name="semantic.png")
        image_id = image.id
        session.flush()
        session.add(
            ReviewCaseEntity(
                id="semantic-resolved",
                image_file_id=image.id,
                status="resolved",
                reason="dirty_lap",
                outcome="model_error",
                decision_field="dirty",
                model_value="true",
                corrected_value="false",
                driver="Driver",
                driver_normalized="driver",
                car="Car",
                car_normalized="car",
                best_lap="1:00.000",
                lap_index=7,
                business_key=f"dirty_lap:{image.id}:driver:car:60000",
            )
        )
        session.commit()

        inserted, _kept, _removed = ReviewRepository(session).upsert_review_cases([
            ReviewCase(
                reason="dirty_lap",
                source_file="semantic.png",
                track=REL_TRACK,
                race_class="A",
                weather="dry",
                temp_f=None,
                driver="Driver",
                car="Car",
                best_lap="1:00.000",
                image_file_id=image.id,
                lap_index=0,
                trigger="model_marked_dirty",
                model_value="true",
            )
        ])
        session.commit()

        rows = session.exec(select(ReviewCaseEntity)).all()

    assert inserted == 1
    assert sorted(row.business_key for row in rows) == [
        f"dirty_lap:{image_id}:0",
        f"dirty_lap:{image_id}:driver:car:60000",
    ]



def test_query_review_candidates_limits_dirty_lap_review_to_best_laps(tmp_path):
    engine = make_engine(tmp_path)
    result = _rel_result(
        "dirty-best-only.png",
        "dirty-best-only-hash",
        [
            _rel_entry("Driver A", best_lap="1:00.000", best_lap_ms=60000, dirty=True),
            _rel_entry("Driver B", best_lap="0:59.000", best_lap_ms=59000, dirty=True),
        ],
    )
    with Session(engine) as session:
        image = ImageFileRepository(session).upsert(file_hash=result.file_hash, file_name=result.source_file)
        run = RunRepository(session).create(run_id="run-dirty-best-only", backend="lmstudio", model="qwen")
        LapRepository(session).add_result(result, run_id=run.id, image_file_id=image.id)
        session.flush()
        rows = session.exec(select(LapRecordEntity).order_by(LapRecordEntity.lap_index)).all()
        rows[1].is_best_lap = True
        session.add(rows[1])
        session.commit()

        cases = [case for case in LapRepository(session).query_review_candidates() if case.reason == "dirty_lap"]

    assert [case.lap_index for case in cases] == [1]

def test_query_review_candidates_keeps_distinct_canonical_dirty_lap_indexes(tmp_path):
    engine = make_engine(tmp_path)
    result = _rel_result(
        "dedupe.png",
        "dedupe-hash",
        [
            _rel_entry("Driver", best_lap="1:00.000", best_lap_ms=60000, dirty=True),
            _rel_entry("Driver", best_lap="1:00.000", best_lap_ms=60000, dirty=True),
        ],
    )
    with Session(engine) as session:
        image = ImageFileRepository(session).upsert(file_hash=result.file_hash, file_name=result.source_file)
        run = RunRepository(session).create(run_id="run-dedupe", backend="lmstudio", model="qwen")
        LapRepository(session).add_result(result, run_id=run.id, image_file_id=image.id)
        session.flush()
        for row in session.exec(select(LapRecordEntity)).all():
            row.is_best_lap = True
            session.add(row)
        session.commit()

        cases = [case for case in LapRepository(session).query_review_candidates() if case.reason == "dirty_lap"]

    assert [case.lap_index for case in cases] == [0, 1]

def test_refresh_review_cases_applies_review_corrections_before_detecting_candidates(tmp_path):
    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    _seed_runtime_results(
        db,
        "refresh-corrections",
        [_rel_result("numeric.png", "numeric-hash", [_rel_entry("42 LionZera7559")])],
    )

    with Session(db._engine_for_db()) as session:
        image = ImageFileRepository(session).by_hash("numeric-hash")
        assert image is not None
        session.add(
            ReviewCorrectionEntity(
                id="correction-driver",
                stable_key=f"{image.id}:0:driver",
                image_file_id=image.id,
                lap_index=0,
                field="driver",
                model_value="42 LionZera7559",
                corrected_value="LionZera7559",
                error_type="gamertag_wrong",
            )
        )
        session.commit()

    db.refresh_review_cases()
    with Session(db._engine_for_db()) as session:
        open_gamertag = session.exec(
            select(ReviewCaseEntity).where(
                ReviewCaseEntity.status == "open",
                ReviewCaseEntity.reason == "gamertag",
            )
        ).all()
        lap = session.exec(select(LapRecordEntity)).first()

    assert open_gamertag == []
    assert lap.driver == "LionZera7559"
    db.close()
