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
    AttemptStatus,
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

def test_db_bootstrap_creates_core_tables(tmp_path):
    engine = make_engine(tmp_path)

    with Session(engine) as session:
        assert session.exec(select(ImageFileEntity)).all() == []
        assert session.exec(select(ExtractionRunEntity)).all() == []
        assert session.exec(select(ExtractionAttemptEntity)).all() == []
        assert session.exec(select(LapRecordEntity)).all() == []
        assert session.exec(select(ReviewCaseEntity)).all() == []
        assert session.exec(select(ExportArtifactEntity)).all() == []

def test_repositories_persist_run_image_laps_reviews_and_artifacts(tmp_path):
    engine = make_engine(tmp_path)
    result = make_result()

    with Session(engine) as session:
        images = ImageFileRepository(session)
        runs = RunRepository(session)
        laps = LapRepository(session)
        reviews = ReviewRepository(session)
        artifacts = ExportArtifactRepository(session)

        image = images.upsert(
            file_hash=result.file_hash,
            file_name="input.png",
            current_name=result.source_file,
            path=tmp_path / "input.png",
        )
        run = runs.create(run_id="run-1", backend="lmstudio", model="qwen")
        lap_entities = laps.add_result(result, run_id=run.id, image_file_id=image.id)
        review = reviews.add_case(
            ReviewCase(
                reason="dirty_lap",
                source_file=result.source_file,
                track="Lime Rock Park Full Circuit",
                race_class="D",
                weather="dry",
                temp_f=76.0,
                driver="Driver2",
                car="Honda Civic",
                best_lap="00:55.500",
            ),
            lap_record_id=lap_entities[1].id,
        )
        artifact = artifacts.add(
            path=tmp_path / "forza_bestlaps.pdf",
            format="pdf",
            run_id=run.id,
        )
        session.commit()

        assert images.by_hash("hash").id == image.id
        assert runs.latest().id == "run-1"
        assert len(laps.list_by_run("run-1")) == 2
        best_driver_lap = session.exec(
            select(LapRecordEntity)
            .where(LapRecordEntity.driver == "Bujica89")
            .order_by(LapRecordEntity.best_lap_ms.asc())
        ).first()
        assert best_driver_lap is not None
        assert best_driver_lap.best_lap_ms == 56092
        assert reviews.open_cases()[0].id == review.id
        assert artifacts.for_run("run-1")[0].id == artifact.id

def test_session_scope_commits_and_rolls_back(tmp_path):
    engine = make_engine(tmp_path)

    with session_scope(engine) as session:
        ImageFileRepository(session).upsert(file_hash="committed", file_name="a.png")

    with Session(engine) as session:
        assert ImageFileRepository(session).by_hash("committed") is not None

    try:
        with session_scope(engine) as session:
            ImageFileRepository(session).upsert(file_hash="rolled-back", file_name="b.png")
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass

    with Session(engine) as session:
        assert ImageFileRepository(session).by_hash("rolled-back") is None

def test_extraction_run_rejects_result_status_values(tmp_path):
    engine = make_engine(tmp_path)
    with Session(engine) as session:
        repo = RunRepository(session)
        for invalid in ("ok", "error"):
            try:
                repo.create(run_id=f"run-{invalid}", backend="lmstudio", model="qwen", status=invalid)
            except ValueError as exc:
                assert "cannot be result status" in str(exc)
            else:
                raise AssertionError(f"status {invalid!r} should have been rejected")

def test_review_reason_trigger_constraints_are_separate(tmp_path):
    engine = make_engine(tmp_path)

    with Session(engine) as session:
        session.add(
            ReviewCaseEntity(
                id="valid-review-trigger",
                case_number=1,
                reason="track",
                trigger="track_unresolved",
                decision_field="track",
                business_key="valid-review-trigger",
            )
        )
        session.commit()

        session.add(
            ReviewCaseEntity(
                id="invalid-review-reason",
                reason="track_unresolved",
                trigger="track_unresolved",
                business_key="invalid-review-reason",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            ReviewCaseEntity(
                id="invalid-review-trigger",
                reason="track",
                trigger="track_uncertain",
                business_key="invalid-review-trigger",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            ReviewCaseEntity(
                id="valid-review-driver-decision-field",
                case_number=2,
                reason="driver_name",
                trigger="numeric_prefix",
                decision_field="driver",
                business_key="valid-review-driver-decision-field",
            )
        )
        session.commit()

        session.add(
            ReviewCaseEntity(
                id="invalid-review-decision-field",
                reason="track",
                trigger="track_unresolved",
                decision_field="legacy_endpoint_field",
                business_key="invalid-review-decision-field",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

def test_review_correction_field_and_cause_constraints(tmp_path):
    engine = make_engine(tmp_path)

    with Session(engine) as session:
        session.add(ImageFileEntity(id="image-review-correction", file_hash="hash-review-correction"))
        session.commit()

        session.add(
            ReviewCorrectionEntity(
                id="valid-review-correction",
                stable_key="image-review-correction:0:driver",
                image_file_id="image-review-correction",
                lap_index=0,
                field="driver",
                corrected_value="Bujica89",
                cause="review",
            )
        )
        session.commit()

        session.add(
            ReviewCorrectionEntity(
                id="invalid-review-correction-field",
                stable_key="image-review-correction:0:legacy_field",
                image_file_id="image-review-correction",
                lap_index=0,
                field="legacy_field",
                corrected_value="value",
                cause="review",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            ReviewCorrectionEntity(
                id="invalid-review-correction-cause",
                stable_key="image-review-correction:0:driver:legacy_cause",
                image_file_id="image-review-correction",
                lap_index=0,
                field="driver",
                corrected_value="value",
                cause="legacy_cause",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

def test_review_case_number_is_unique(tmp_path):
    engine = make_engine(tmp_path)

    with Session(engine) as session:
        session.add(
            ReviewCaseEntity(
                id="review-case-number-1",
                case_number=1,
                reason="track",
                trigger="track_unknown",
                business_key="review-case-number-1",
            )
        )
        session.commit()

        session.add(
            ReviewCaseEntity(
                id="review-case-number-duplicate",
                case_number=1,
                reason="weather",
                trigger="weather_unknown",
                business_key="review-case-number-duplicate",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            ReviewCaseEntity(
                id="review-case-number-2",
                case_number=2,
                reason="weather",
                trigger="weather_unknown",
                business_key="review-case-number-2",
            )
        )
        session.commit()

def test_review_case_domain_enums_validate_trigger_outcome_and_decision_field() -> None:
    case = ReviewCase(
        reason=ReviewReason.DRIVER_NAME,
        source_file="sample.png",
        track="Lime Rock Park Full Circuit",
        race_class=RaceClass.D,
        weather=WeatherType.DRY,
        temp_f=76,
        driver="123Driver",
        car="Mazda",
        best_lap="00:56.000",
        trigger="numeric_prefix",
        outcome="model_error",
        decision_field="driver",
    )

    assert case.trigger is ReviewTrigger.NUMERIC_PREFIX
    assert case.outcome is ReviewOutcome.MODEL_ERROR
    assert case.decision_field is ReviewDecisionField.DRIVER
    assert str(case.trigger) == "numeric_prefix"
    assert str(case.outcome) == "model_error"
    assert str(case.decision_field) == "driver"

    with pytest.raises(ValidationError):
        ReviewCase(
            reason=ReviewReason.TRACK,
            source_file="sample.png",
            track="Unknown",
            race_class=RaceClass.D,
            weather=WeatherType.DRY,
            temp_f=None,
            driver=None,
            car=None,
            best_lap=None,
            trigger="track_uncertain",
        )

    with pytest.raises(ValidationError):
        ReviewCase(
            reason=ReviewReason.TRACK,
            source_file="sample.png",
            track="Unknown",
            race_class=RaceClass.D,
            weather=WeatherType.DRY,
            temp_f=None,
            driver=None,
            car=None,
            best_lap=None,
            outcome="accepted",
        )

    with pytest.raises(ValidationError):
        ReviewCase(
            reason=ReviewReason.TRACK,
            source_file="sample.png",
            track="Unknown",
            race_class=RaceClass.D,
            weather=WeatherType.DRY,
            temp_f=None,
            driver=None,
            car=None,
            best_lap=None,
            decision_field="driver_name",
        )

def test_image_file_domain_status_enums_validate_values() -> None:
    image = ImageFile(
        id="image-status-enum",
        file_hash="hash-status-enum",
        current_name="sample.png",
        file_status="missing",
        best_lap_status="contributing",
    )

    assert image.file_status is ImageFileStatus.MISSING
    assert image.best_lap_status is BestLapStatus.CONTRIBUTING
    assert str(image.file_status) == "missing"
    assert str(image.best_lap_status) == "contributing"

    image.file_status = "available"
    image.best_lap_status = "non_contributing"
    assert image.file_status is ImageFileStatus.AVAILABLE
    assert image.best_lap_status is BestLapStatus.NON_CONTRIBUTING

    with pytest.raises(ValidationError):
        ImageFile(
            id="bad-file-status",
            file_hash="hash-bad-file-status",
            current_name="sample.png",
            file_status="archived",
        )

    with pytest.raises(ValidationError):
        ImageFile(
            id="bad-best-lap-status",
            file_hash="hash-bad-best-lap-status",
            current_name="sample.png",
            best_lap_status="winner",
        )

def test_model_extraction_attempt_status_enum_validates_values() -> None:
    attempt = ModelExtractionAttempt(
        attempt_number=1,
        status="ok",
    )

    assert attempt.status is AttemptStatus.OK
    assert str(attempt.status) == "ok"

    attempt.status = "cancelled"
    assert attempt.status is AttemptStatus.CANCELLED

    with pytest.raises(ValidationError):
        ModelExtractionAttempt(
            attempt_number=2,
            status="pending",
        )

    with pytest.raises(ValidationError):
        attempt.status = "running"

def test_extraction_run_schema_uses_canonical_prompt_and_error_names(tmp_path):
    engine = make_engine(tmp_path)

    with Session(engine) as session:
        repository = RunRepository(session)
        entity = repository.create(
            run_id="canonical-run-schema",
            backend="lmstudio",
            model="qwen",
            prompt_name="main",
        )
        entity.operational_error_message = "connection refused"
        session.add(entity)
        session.commit()

        schema = repository.to_schema(entity)
        payload = dump_schema(schema)

    assert schema.prompt_name == "main"
    assert schema.operational_error_message == "connection refused"
    assert not hasattr(schema, "prompt" + "_version")
    assert not hasattr(schema, "error_message")
    assert payload["prompt_name"] == "main"
    assert payload["operational_error_message"] == "connection refused"
    assert "prompt" + "_version" not in payload
    assert "error_message" not in payload

def test_extraction_result_metrics_persist_from_model_response_stats(tmp_path):
    engine = make_engine(tmp_path)
    result = replace(
        make_result(),
        model_response_stats=ModelResponseStats(
            duration_ms=1234,
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            reasoning_output_tokens=4,
            tokens_per_second=12.5,
            time_to_first_token_seconds=0.75,
            model_load_time_seconds=1.25,
        ),
    )

    with Session(engine) as session:
        image = ImageFileRepository(session).upsert(
            file_hash=result.file_hash,
            file_name="input.png",
            current_name=result.source_file,
        )
        run = RunRepository(session).create(run_id="run-model-stats", backend="lmstudio", model="qwen")
        entity = ExtractionResultRepository(session).add_result(
            result,
            run_id=run.id,
            image_file_id=image.id,
        )
        session.commit()

        persisted = session.get(type(entity), entity.id)
        assert persisted is not None
        metrics = {
            "duration_ms": persisted.duration_ms,
            "input_tokens": persisted.input_tokens,
            "output_tokens": persisted.output_tokens,
            "total_tokens": persisted.total_tokens,
            "reasoning_tokens": persisted.reasoning_tokens,
            "tokens_per_second": persisted.tokens_per_second,
            "time_to_first_token_s": persisted.time_to_first_token_s,
            "model_load_time_s": persisted.model_load_time_s,
        }

    assert metrics == {
        "duration_ms": 1234,
        "input_tokens": 10,
        "output_tokens": 20,
        "total_tokens": 30,
        "reasoning_tokens": 4,
        "tokens_per_second": 12.5,
        "time_to_first_token_s": 0.75,
        "model_load_time_s": 1.25,
    }


def test_run_repository_latest_uses_created_at_when_started_at_is_null(tmp_path):
    engine = make_engine(tmp_path)
    now = datetime.now(timezone.utc)

    with Session(engine) as session:
        older = RunRepository(session).create(run_id="older-running", backend="lmstudio", model="qwen")
        older.created_at = now - timedelta(minutes=10)
        older.started_at = now - timedelta(minutes=9)
        newer = RunRepository(session).create(run_id="newer-pending", backend="lmstudio", model="qwen")
        newer.created_at = now
        newer.started_at = None
        session.commit()

        assert RunRepository(session).latest().id == "newer-pending"
