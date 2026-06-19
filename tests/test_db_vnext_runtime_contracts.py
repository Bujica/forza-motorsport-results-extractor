from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from forza.application import DatabaseService
from forza.application.run_control import RunControl
from forza.db import create_sqlite_engine
from forza.db.evidence import canonical_request_hash
from forza.db.migrate import upgrade_database
from forza.db.models import (
    ExtractionAttemptEntity,
    ExtractionResultEntity,
    ExtractionRunEntity,
    ImageFlagEntity,
    LapRecordEntity,
    ModelArtifactEntity,
    PromptSnapshotEntity,
    ReviewCaseEntity,
    RunInputEntity,
)
from forza.application.run_service import _account_for_unselected_files
from forza.pipeline import DiscoveredImage, ImageDiscoveryPlan, SkippedImage, plan_images
from forza.schemas import (
    ExtractionResult,
    LapRecord,
    ModelExtractionAttempt,
    RaceSession,
    RunStatus,
)


def _database(tmp_path: Path) -> DatabaseService:
    path = tmp_path / "forza.sqlite3"
    upgrade_database(path)
    return DatabaseService(path)


def _begin_run_with_inputs(
    db: DatabaseService,
    tmp_path: Path,
    run_id: str,
    count: int,
) -> list[tuple[Path, str]]:
    db.begin_run(
        run_id=run_id,
        backend="lmstudio",
        model="model-a",
        prompt_name="test",
        input_dir=str(tmp_path),
    )
    images: list[tuple[Path, str]] = []
    for index in range(count):
        path = tmp_path / f"{run_id}-{index}.png"
        path.write_bytes(f"image-{run_id}-{index}".encode("ascii"))
        images.append((path, f"hash-{run_id}-{index}"))
    db.record_discovery_inputs(
        run_id=run_id,
        discovery=ImageDiscoveryPlan(
            total=count,
            new_images=[DiscoveredImage(path, file_hash) for path, file_hash in images],
            duplicates=[],
            existing_images=[],
        ),
    )
    db.record_runtime_snapshot(
        run_id=run_id,
        diagnostic=SimpleNamespace(
            endpoint="http://localhost:1234/api/v1/models",
            configured_model="model-a",
            model_found=True,
            model_label="Model A",
            instance_id="instance-a",
            desired_config={},
            effective_config={},
            ok=True,
            message="ready",
            warnings=(),
            errors=(),
        ),
    )
    return images


def _attempt(prepared, file_hash: str, *, artifact_path: Path | None = None) -> ModelExtractionAttempt:
    messages = [{"type": "image", "data_url": "[image redacted]"}]
    config = {"temperature": 0.0}
    return ModelExtractionAttempt(
        attempt_number=1,
        attempt_reason="initial",
        status="ok",
        accepted=True,
        runtime_snapshot_id=prepared.runtime_snapshot_id,
        model="model-a",
        model_instance_id="instance-a",
        request_image_format="png",
        request_image_mime_type="image/png",
        request_image_width_px=1920,
        request_image_height_px=1080,
        request_image_bytes=100,
        request_config_json=config,
        request_messages_json=messages,
        request_hash=canonical_request_hash(
            request_messages_json=messages,
            request_config_json=config,
            prompt_snapshot_id=prepared.prompt_snapshot_id,
            model="model-a",
            source_file_hash=file_hash,
            request_image_format="png",
            request_image_mime_type="image/png",
            request_image_width=1920,
            request_image_height=1080,
            request_image_bytes=100,
        ),
        raw_response='{"t":"Track","e":[]}',
        parsed_json={"t": "Track", "e": []},
        artifact_path=str(artifact_path) if artifact_path else None,
        artifact_type="raw_response" if artifact_path else None,
        artifact_is_canonical=artifact_path is not None,
    )


def _ok_result(path: Path, file_hash: str, attempt: ModelExtractionAttempt) -> ExtractionResult:
    return ExtractionResult(
        source_file=path.name,
        file_hash=file_hash,
        session=RaceSession(
            track="Track",
            temp_f=70.0,
            temp_c=21.1,
            entries=[LapRecord("Driver", "Car", "A", "1:00.000", 60.0)],
            race_class="A",
            weather="dry",
        ),
        status="ok",
        current_path=str(path),
        raw_response=attempt.raw_response,
        model_name="model-a",
        model_attempts=[attempt],
    )


def test_attempts_are_incremental_append_only_and_artifact_tracked(tmp_path: Path) -> None:
    db = _database(tmp_path)
    path, file_hash = _begin_run_with_inputs(db, tmp_path, "run-1", 1)[0]
    artifact = tmp_path / "raw.json"
    artifact.write_text('{"raw":true}', encoding="utf-8")
    prepared = db.prepare_extraction_result(run_id="run-1", file_hash=file_hash, path=path)

    attempt = _attempt(prepared, file_hash, artifact_path=artifact)
    attempt_id = db.record_extraction_attempt(prepared=prepared, attempt=attempt, run_id="run-1")
    assert db.record_extraction_attempt(prepared=prepared, attempt=attempt, run_id="run-1") == attempt_id
    db.upsert_image_and_laps(_ok_result(path, file_hash, attempt), run_id="run-1")
    db.complete_run("run-1")

    with Session(db._engine_for_db()) as session:
        result = session.get(ExtractionResultEntity, prepared.extraction_result_id)
        attempts = session.exec(select(ExtractionAttemptEntity)).all()
        artifacts = session.exec(select(ModelArtifactEntity)).all()
    assert result.status == "ok"
    assert result.accepted_attempt_id == attempt_id
    assert result.attempt_count == 1
    assert len(attempts) == 1
    assert attempts[0].runtime_snapshot_id == prepared.runtime_snapshot_id
    assert len(artifacts) == 1
    assert artifacts[0].sha256 and artifacts[0].size_bytes == artifact.stat().st_size
    db.close()


def test_preflight_failure_creates_no_results_and_no_process_decisions(tmp_path: Path) -> None:
    db = _database(tmp_path)
    _begin_run_with_inputs(db, tmp_path, "run-preflight", 2)
    db.fail_preflight_run("run-preflight", error="lmstudio_preflight_failed: unavailable")

    with Session(db._engine_for_db()) as session:
        run = session.get(ExtractionRunEntity, "run-preflight")
        inputs = session.exec(select(RunInputEntity)).all()
        results = session.exec(select(ExtractionResultEntity)).all()
    assert run.status == "failed"
    assert run.operational_error_code == "lmstudio_preflight_failed"
    assert {row.decision for row in inputs} == {"skip"}
    assert {row.skip_reason for row in inputs} == {"preflight_failed"}
    assert results == []
    db.close()


def test_cancel_and_abandoned_recovery_finalize_every_process_input(tmp_path: Path) -> None:
    db = _database(tmp_path)
    images = _begin_run_with_inputs(db, tmp_path, "run-cancel", 2)
    db.prepare_extraction_result(run_id="run-cancel", file_hash=images[0][1], path=images[0][0])
    db.reconcile_interrupted_run(
        "run-cancel",
        status=RunStatus.CANCELLED,
        error="cancelled_by_user",
    )

    abandoned = _begin_run_with_inputs(db, tmp_path, "run-abandoned", 1)[0]
    db.prepare_extraction_result(
        run_id="run-abandoned",
        file_hash=abandoned[1],
        path=abandoned[0],
    )
    assert db.reconcile_abandoned_runs() == 1

    with Session(db._engine_for_db()) as session:
        cancelled = session.get(ExtractionRunEntity, "run-cancel")
        recovered = session.get(ExtractionRunEntity, "run-abandoned")
        results = session.exec(select(ExtractionResultEntity)).all()
    assert cancelled.status == "cancelled"
    assert cancelled.processed == 2
    assert recovered.status == "failed"
    assert recovered.operational_error_code == "abandoned_run_recovered"
    assert len(results) == 3
    assert {row.status for row in results} == {"cancelled"}
    db.close()


def test_complete_run_refuses_nonfinal_results(tmp_path: Path) -> None:
    db = _database(tmp_path)
    path, file_hash = _begin_run_with_inputs(db, tmp_path, "run-nonfinal", 1)[0]
    db.prepare_extraction_result(run_id="run-nonfinal", file_hash=file_hash, path=path)

    with pytest.raises(RuntimeError, match="result\\(s\\) are not final"):
        db.complete_run("run-nonfinal")

    db.reconcile_interrupted_run(
        "run-nonfinal",
        status=RunStatus.FAILED,
        error="test_cleanup",
    )
    db.close()


def test_review_refresh_is_global_and_auto_resolves_flags(tmp_path: Path) -> None:
    db = _database(tmp_path)
    for run_id in ("run-a", "run-b"):
        path, file_hash = _begin_run_with_inputs(db, tmp_path, run_id, 1)[0]
        prepared = db.prepare_extraction_result(run_id=run_id, file_hash=file_hash, path=path)
        attempt = _attempt(prepared, file_hash)
        result = _ok_result(path, file_hash, attempt)
        result.session.entries[0].dirty = True
        db.record_extraction_attempt(prepared=prepared, attempt=attempt, run_id=run_id)
        db.upsert_image_and_laps(result, run_id=run_id)
        db.complete_run(run_id)

    # Dirty-lap review is intentionally output-impacting only. This runtime
    # contract exercises global refresh/flag resolution, so its fixtures must
    # declare the dirty rows as current Best Laps.
    with Session(db._engine_for_db()) as session:
        for lap_row in session.exec(select(LapRecordEntity)).all():
            lap_row.is_best_lap = True
            session.add(lap_row)
        session.commit()

    db.refresh_review_cases(run_id="run-a")
    assert db.count_review_cases(status="open") == 2
    assert db.count_review_cases(run_id="run-a", status="open") == 1
    assert db.count_review_cases(run_id="run-b", status="open") == 1
    with Session(db._engine_for_db()) as session:
        cases = session.exec(select(ReviewCaseEntity)).all()
        assert len([row for row in cases if row.status == "open"]) == 2
        assert session.get(ExtractionRunEntity, "run-a").review_case_count == 1
        assert session.get(ExtractionRunEntity, "run-b").review_case_count == 1
        lap = cases[0].lap_record_id
        lap_row = session.get(LapRecordEntity, lap)
        lap_row.dirty = False
        session.add(lap_row)
        session.commit()

    db.refresh_review_cases(run_id="run-a")
    with Session(db._engine_for_db()) as session:
        cases = session.exec(select(ReviewCaseEntity)).all()
        flags = session.exec(select(ImageFlagEntity)).all()
        counts = {
            run_id: session.get(ExtractionRunEntity, run_id).review_case_count
            for run_id in ("run-a", "run-b")
        }
    assert len([row for row in cases if row.status == "open"]) == 1
    assert len([row for row in cases if row.status == "auto_resolved"]) == 1
    assert len([row for row in flags if row.status == "active"]) == 1
    assert len([row for row in flags if row.status == "resolved"]) == 1
    assert sorted(counts.values()) == [0, 1]
    assert db.count_review_cases(run_id="run-a", status="open") == 0
    assert db.count_review_cases(run_id="run-b", status="open") == 1
    db.close()


def test_request_hash_changes_with_image_file_evidence() -> None:
    common = {
        "request_messages_json": [{"type": "image", "data_url": "[image redacted]"}],
        "request_config_json": {"temperature": 0.0},
        "prompt_snapshot_id": "prompt:abc",
        "model": "model-a",
        "request_image_format": "png",
        "request_image_mime_type": "image/png",
        "request_image_width": 1920,
        "request_image_height": 1080,
        "request_image_bytes": 100,
    }
    assert canonical_request_hash(source_file_hash="hash-a", **common) != canonical_request_hash(
        source_file_hash="hash-b",
        **common,
    )


def test_normal_database_service_never_auto_upgrades(tmp_path: Path) -> None:
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(RuntimeError, match="maintenance db-upgrade"):
        DatabaseService(path).begin_run(
            run_id="run",
            backend="lmstudio",
            model="model-a",
            prompt_name="test",
            input_dir=str(tmp_path),
        )
    assert not path.exists()


def test_baseline_migration_uses_frozen_sql_snapshot() -> None:
    root = Path(__file__).resolve().parents[1]
    migration = (
        root / "forza" / "db" / "migrations" / "versions" / "0001_db_vnext_baseline.py"
    ).read_text(encoding="utf-8")
    schema = root / "forza" / "db" / "migrations" / "versions" / "0001_db_vnext_schema.sql"

    assert "SQLModel.metadata" not in migration
    assert schema.exists()
    assert "CREATE TABLE extraction_runs" in schema.read_text(encoding="utf-8")


def test_discovery_accounts_hash_failures_and_unsupported_files(tmp_path: Path, monkeypatch) -> None:
    valid = tmp_path / "valid.png"
    broken = tmp_path / "broken.png"
    unsupported = tmp_path / "notes.txt"
    for path in (valid, broken, unsupported):
        path.write_text(path.name, encoding="utf-8")

    def hash_or_fail(path: Path) -> str:
        if path == broken:
            raise PermissionError("locked")
        return f"hash-{path.name}"

    monkeypatch.setattr("forza.pipeline.image.file_hash", hash_or_fail)
    plan = plan_images([valid, broken], set())
    accounted = _account_for_unselected_files(
        plan,
        all_files=[valid, broken, unsupported],
        selected_images=[valid, broken],
    )

    assert accounted.total == 3
    assert [row.path for row in accounted.new_images] == [valid]
    assert {(row.path, row.reason) for row in accounted.skipped_images} == {
        (broken, "hash_failed"),
        (unsupported, "unsupported_extension"),
    }
    assert accounted.total == 3


def test_discovery_persists_contract_decisions_and_missing_file_accounting(tmp_path: Path) -> None:
    db = _database(tmp_path)
    db.begin_run(
        run_id="run-input-contract",
        backend="lmstudio",
        model="model-a",
        prompt_name="test",
        input_dir=str(tmp_path),
    )
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("notes", encoding="utf-8")
    missing = tmp_path / "missing.png"
    db.record_discovery_inputs(
        run_id="run-input-contract",
        discovery=ImageDiscoveryPlan(
            total=2,
            new_images=[],
            duplicates=[],
            existing_images=[],
            skipped_images=[
                SkippedImage(unsupported, "unsupported_extension"),
                SkippedImage(missing, "retry_missing", "hash-missing"),
            ],
        ),
    )

    with Session(db._engine_for_db()) as session:
        rows = session.exec(select(RunInputEntity).order_by(RunInputEntity.input_order)).all()
        run = session.get(ExtractionRunEntity, "run-input-contract")
    assert [row.decision for row in rows] == ["unsupported", "missing"]
    assert rows[0].size_bytes == unsupported.stat().st_size
    assert rows[1].size_bytes is None
    assert run.total_inputs == 2
    assert run.skipped == 2
    db.close()


def test_retry_accounting_total_includes_missing_failed_images(tmp_path: Path) -> None:
    selected = tmp_path / "retry.png"
    selected.write_bytes(b"image")
    missing = tmp_path / "missing.png"
    discovery = ImageDiscoveryPlan(
        total=2,
        new_images=[DiscoveredImage(selected, "hash-retry")],
        duplicates=[],
        existing_images=[],
        skipped_images=[SkippedImage(missing, "retry_missing", "hash-missing")],
    )

    accounted = _account_for_unselected_files(
        discovery,
        all_files=[selected],
        selected_images=[selected],
    )

    assert accounted.total == 2


def test_run_control_elapsed_excludes_paused_time(monkeypatch) -> None:
    clock = iter([10.0, 30.0, 50.0])
    monkeypatch.setattr("forza.application.run_control.time.monotonic", clock.__next__)
    control = RunControl()

    control.pause()   # pause starts at 10
    control.resume()  # pause ends at 30

    assert control.paused_duration_s == 20.0
    assert control.elapsed_since(0.0) == 30.0


def test_registered_model_artifact_cannot_be_rehashed_after_mutation(tmp_path: Path) -> None:
    db = _database(tmp_path)
    [(path, file_hash)] = _begin_run_with_inputs(db, tmp_path, "run-artifact-immutable", 1)
    prepared = db.prepare_extraction_result(
        run_id="run-artifact-immutable",
        file_hash=file_hash,
        path=path,
    )
    artifact = tmp_path / "attempt.json"
    artifact.write_text('{"version": 1}', encoding="utf-8")
    attempt = ModelExtractionAttempt(
        attempt_number=1,
        status="error",
        accepted=False,
        rejected_reason="parse_error",
        artifact_path=str(artifact),
        artifact_type="failed_attempt",
    )

    db.record_extraction_attempt(
        prepared=prepared,
        attempt=attempt,
        run_id="run-artifact-immutable",
    )
    artifact.write_text('{"version": 2}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="immutable"):
        db.record_extraction_attempt(
            prepared=prepared,
            attempt=attempt,
            run_id="run-artifact-immutable",
        )
    db.close()


def test_export_snapshot_cannot_mask_mutated_content_addressed_file(tmp_path: Path) -> None:
    db = _database(tmp_path)
    source = tmp_path / "report.csv"
    source.write_text("version,1\n", encoding="utf-8")

    db.record_artifact(path=source, format="csv")
    [snapshot] = (tmp_path / "artifacts").glob("report__manual__*.csv")
    snapshot.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="immutable"):
        db.record_artifact(path=source, format="csv")
    db.close()


def test_begin_run_rejects_mutated_prompt_snapshot(tmp_path: Path) -> None:
    db = _database(tmp_path)
    db.begin_run(
        run_id="run-prompt-original",
        backend="lmstudio",
        model="model-a",
        prompt_name="test",
        input_dir=str(tmp_path),
    )
    with Session(db._engine_for_db()) as session:
        prompt = session.exec(select(PromptSnapshotEntity)).one()
        prompt.system_text = "tampered"
        session.add(prompt)
        session.commit()

    with pytest.raises(RuntimeError, match="immutable"):
        db.begin_run(
            run_id="run-prompt-reuse",
            backend="lmstudio",
            model="model-a",
            prompt_name="test",
            input_dir=str(tmp_path),
        )
    db.close()
