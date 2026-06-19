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

def test_database_service_begin_complete_run(tmp_path):
    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    db.begin_run(
        run_id="lifecycle_run",
        backend="lmstudio",
        model="qwen",
        prompt_name="user_header_shaped_v1",
        input_dir="data/input",
    )
    status_mid = db.status()
    assert status_mid.extraction_runs == 1

    db.complete_run("lifecycle_run", metrics={"succeeded": 5})
    assert db.latest_completed_run_id() == "lifecycle_run"
    db.close()

    # Re-open and verify
    db2 = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    status_final = db2.status()
    assert status_final.extraction_runs == 1
    assert db2.latest_completed_run_id() == "lifecycle_run"
    db2.close()

def test_database_service_begin_run_records_prompt_snapshot(tmp_path):
    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    db.begin_run(
        run_id="prompt-run",
        backend="lmstudio",
        model="qwen",
        prompt_name="user_header_shaped_v1",
        input_dir="data/input",
    )

    with Session(db._engine_for_db()) as session:
        run = session.get(ExtractionRunEntity, "prompt-run")
        snapshot = session.get(PromptSnapshotEntity, run.prompt_snapshot_id)

    assert run.prompt_name == "user_header_shaped_v1"
    assert run.prompt_hash
    assert snapshot.prompt_name == "user_header_shaped_v1"
    assert snapshot.system_text.startswith("Return ONLY a minified JSON")
    db.close()

def test_database_service_records_discovery_run_inputs(tmp_path):
    from forza.pipeline.image import DiscoveredImage, DuplicateImage, ExistingImage, ImageDiscoveryPlan

    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    db.begin_run(
        run_id="inputs-run",
        backend="lmstudio",
        model="qwen",
        prompt_name="v1",
        input_dir=str(tmp_path),
    )
    new_path = tmp_path / "new.png"
    existing_path = tmp_path / "existing.png"
    duplicate_path = tmp_path / "duplicate.png"
    for path in (new_path, existing_path, duplicate_path):
        path.write_bytes(path.name.encode("utf-8"))
    db.register_image_file(file_hash="hash-existing", path=existing_path)

    db.record_discovery_inputs(
        run_id="inputs-run",
        discovery=ImageDiscoveryPlan(
            total=3,
            new_images=[DiscoveredImage(new_path, "hash-new")],
            existing_images=[ExistingImage(existing_path, "hash-existing")],
            duplicates=[DuplicateImage(duplicate_path, "hash-existing", "cache", duplicate_of_hash="hash-existing")],
        ),
    )

    with Session(db._engine_for_db()) as session:
        rows = session.exec(select(RunInputEntity).order_by(RunInputEntity.input_order)).all()
        run = session.get(ExtractionRunEntity, "inputs-run")

    assert [row.decision for row in rows] == ["process", "skip", "duplicate"]
    assert rows[0].image_file_id is not None
    assert rows[1].skip_reason == "existing_ok"
    assert rows[2].duplicate_kind == "hash"
    assert rows[2].duplicate_of_input_id == rows[1].id
    assert run.total_inputs == 3
    assert run.to_process == 1
    db.close()

def test_database_service_records_runtime_snapshot(tmp_path):
    from types import SimpleNamespace

    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    db.begin_run(
        run_id="runtime-run",
        backend="lmstudio",
        model="qwen",
        prompt_name="v1",
        input_dir="input",
    )
    snapshot_id = db.record_runtime_snapshot(
        run_id="runtime-run",
        diagnostic=SimpleNamespace(
            endpoint="http://localhost:1234/api/v1/models",
            configured_model="qwen",
            model_label="Qwen",
            instance_id="instance-1",
            desired_config={"context_length": 5000},
            effective_config={"context_length": 5000},
            ok=True,
            message="Qwen loaded",
            capabilities_summary="vision=yes",
            warnings=(),
            errors=(),
        ),
    )

    with Session(db._engine_for_db()) as session:
        snapshot = session.get(ModelRuntimeSnapshotEntity, snapshot_id)

    assert snapshot.run_id == "runtime-run"
    assert snapshot.snapshot_kind == "preflight"
    assert snapshot.health_ok is True
    assert snapshot.instance_id == "instance-1"
    db.close()

def test_database_service_fail_run(tmp_path):
    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    db.begin_run(
        run_id="failing_run",
        backend="lmstudio",
        model="qwen",
        prompt_name="v1",
        input_dir="data/input",
    )
    db.fail_run("failing_run", error="Something exploded")
    db.close()

def test_database_service_upsert_image_and_laps(tmp_path):
    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    # Create a run first (lap_records FK requires it)
    db.begin_run(
        run_id="realtime_run",
        backend="lmstudio",
        model="qwen",
        prompt_name="v1",
        input_dir="data/input",
    )
    inserted = db.upsert_image_and_laps(make_result(), run_id="realtime_run")
    assert inserted == 2

    # Second call with same data must not duplicate
    inserted_again = db.upsert_image_and_laps(make_result(), run_id="realtime_run")
    assert inserted_again == 0  # duplicates silently ignored

    status = db.status()
    assert status.lap_records == 2
    db.close()

def test_database_service_does_not_swallow_lap_integrity_errors(tmp_path, monkeypatch):
    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    db.begin_run(
        run_id="integrity-run",
        backend="lmstudio",
        model="qwen",
        prompt_name="v1",
        input_dir="data/input",
    )

    def fail_add_result(*_args, **_kwargs):
        raise IntegrityError("insert lap", {}, Exception("constraint failed"))

    monkeypatch.setattr(LapRepository, "add_result", fail_add_result)

    with pytest.raises(IntegrityError):
        db.upsert_image_and_laps(make_result(), run_id="integrity-run")
    db.close()

def test_database_service_registers_raw_response_artifact(tmp_path):
    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    raw_path = tmp_path / "debug" / "raw.json"
    raw_path.parent.mkdir()
    raw_path.write_text('{"raw":true}', encoding="utf-8")
    db.begin_run(
        run_id="artifact-run",
        backend="lmstudio",
        model="qwen",
        prompt_name="v1",
        input_dir=str(tmp_path),
    )
    result = make_result()
    result.raw_response = '{"raw":true}'
    result.raw_response_artifact_path = str(raw_path)
    db.upsert_image_and_laps(result, run_id="artifact-run")

    with Session(db._engine_for_db()) as session:
        artifact = session.exec(select(ModelArtifactEntity)).one()

    assert artifact.artifact_type == "raw_response"
    assert artifact.is_canonical is True
    assert artifact.size_bytes == raw_path.stat().st_size
    assert artifact.sha256
    db.close()

def test_database_service_lists_only_latest_failed_images_for_retry(tmp_path):
    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    fixed_path = tmp_path / "fixed.png"
    failed_path = tmp_path / "failed.png"
    fixed_path.write_bytes(b"fixed")
    failed_path.write_bytes(b"failed")
    db.begin_run(
        run_id="first-run",
        backend="lmstudio",
        model="qwen",
        prompt_name="v1",
        input_dir=str(tmp_path),
    )
    db.upsert_image_and_laps(
        ExtractionResult(
            "fixed.png",
            "hash-fixed",
            None,
            "error",
            error="LM Studio returned no model",
            current_path=str(fixed_path),
        ),
        run_id="first-run",
    )
    db.upsert_image_and_laps(
        ExtractionResult(
            "failed.png",
            "hash-failed",
            None,
            "error",
            error="LM Studio returned no model",
            current_path=str(failed_path),
        ),
        run_id="first-run",
    )
    db.complete_run("first-run")
    db.begin_run(
        run_id="second-run",
        backend="lmstudio",
        model="qwen",
        prompt_name="v1",
        input_dir=str(tmp_path),
    )
    fixed_ok = make_result()
    fixed_ok.file_hash = "hash-fixed"
    fixed_ok.source_file = "fixed.png"
    fixed_ok.current_path = str(fixed_path)
    db.upsert_image_and_laps(fixed_ok, run_id="second-run")

    retry = db.list_failed_images_for_retry()

    assert retry == [(failed_path, "hash-failed")]
    db.close()

def test_db_status_does_not_create_database(tmp_path):
    """db-status must not create the database file."""
    db_path = tmp_path / "forza.sqlite3"
    status = DatabaseService(db_path).status()

    assert not db_path.exists()
    assert status.database_exists is False
    assert status.lap_records == 0
    assert status.extraction_runs == 0

def test_database_service_context_manager(tmp_path):
    with DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True) as db:
        db.begin_run(
            run_id="ctx_run",
            backend="lmstudio",
            model="qwen",
            prompt_name="v1",
            input_dir="data/input",
        )

def test_run_lifecycle_metrics_are_recomputed_from_relational_rows(tmp_path):
    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    db.begin_run(
        run_id="metrics_run",
        backend="lmstudio",
        model="qwen",
        prompt_name="prompt-v2",
        input_dir="data/input",
    )
    db.complete_run(
        "metrics_run",
        metrics={
            "processed": 4,
            "succeeded": 3,
            "failed": 1,
            "review_case_count": 2,
        },
    )
    engine = db._engine_for_db()
    with Session(engine) as session:
        row = session.get(ExtractionRunEntity, "metrics_run")
        assert row.status == "completed"
        assert row.prompt_name == "prompt-v2"
        assert row.input_dir == "data/input"
        assert row.processed == 0
        assert row.succeeded == 0
        assert row.failed == 0
        assert row.review_case_count == 0
        assert row.finished_at is not None
    db.close()

def test_db_status_reports_schema_revision(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    db = DatabaseService(db_path, auto_upgrade=True)
    missing = db.status()
    assert missing.schema_state == "missing"
    assert missing.head_revision is not None

    db.begin_run(
        run_id="schema-run",
        backend="lmstudio",
        model="qwen",
        prompt_name="v1",
        input_dir="input",
    )
    current = db.status()
    assert current.schema_state == "current"
    assert current.current_revision == current.head_revision
    db.close()


def test_database_service_persists_model_attempts(tmp_path):
    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    db.begin_run(
        run_id="attempt-run",
        backend="lmstudio",
        model="qwen",
        prompt_name="v1",
        input_dir="data/input",
    )
    result = make_result()
    result.model_attempts = [
        ModelExtractionAttempt(
            attempt_number=1,
            attempt_reason="initial",
            status="error",
            rejected_reason="parse_error",
            model_instance_id="qwen/qwen3.5-9b",
            parse_error="bad json",
        ),
        ModelExtractionAttempt(
            attempt_number=2,
            attempt_reason="json_retry",
            status="ok",
            accepted=True,
            model_instance_id="qwen/qwen3.5-9b",
            tokens_per_second=30.5,
            time_to_first_token_seconds=0.3,
            parsed_json={"t": "Track", "e": []},
        ),
    ]

    db.upsert_image_and_laps(result, run_id="attempt-run", gamertag="Bujica89")

    with Session(db._engine_for_db()) as session:
        rows = session.exec(
            select(ExtractionAttemptEntity).order_by(ExtractionAttemptEntity.attempt_number)
        ).all()
        assert [row.attempt_reason for row in rows] == ["initial", "json_retry"]
        assert rows[0].accepted is False
        assert rows[1].accepted is True
        assert rows[1].tokens_per_second == 30.5
    db.close()
