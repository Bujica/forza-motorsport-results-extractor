from __future__ import annotations

from pathlib import Path
import sqlite3

from sqlmodel import Session

from forza.application.db_doctor_service import DbDoctorService
from forza.application.db_doctor.schema_checks import _EXPECTED_SCHEMA_MIGRATION_REVISIONS
from forza.db import create_sqlite_engine
from forza.db.evidence import canonical_request_hash
from forza.db.models import (
    ExtractionAttemptEntity,
    ExtractionResultEntity,
    ExtractionRunEntity,
    ImageFlagEntity,
    LapRecordEntity,
    ModelArtifactEntity,
    ModelRuntimeSnapshotEntity,
    PromptSnapshotEntity,
    ReviewCaseEntity,
    RunInputEntity,
    ImageFileEntity,
)
from forza.pipeline import file_hash
from forza.prompts import prompt_payload_hash

__all__ = [
    "Path",
    "sqlite3",
    "Session",
    "DbDoctorService",
    "_EXPECTED_SCHEMA_MIGRATION_REVISIONS",
    "create_sqlite_engine",
    "canonical_request_hash",
    "ExtractionAttemptEntity",
    "ExtractionResultEntity",
    "ExtractionRunEntity",
    "ImageFlagEntity",
    "LapRecordEntity",
    "ModelArtifactEntity",
    "ModelRuntimeSnapshotEntity",
    "PromptSnapshotEntity",
    "ReviewCaseEntity",
    "RunInputEntity",
    "ImageFileEntity",
    "file_hash",
    "prompt_payload_hash",
    "_seed_valid_run",
    "_report_by_key",
]


def _seed_valid_run(db_path: Path) -> dict[str, str | int]:
    raw_path = db_path.parent / "raw.png"
    raw_path.write_bytes(b"image file")
    raw_hash = file_hash(raw_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            prompt_hash = prompt_payload_hash(
                system_text="Extract laps.",
                user_text_template=None,
                response_schema_json=None,
            )
            prompt = PromptSnapshotEntity(
                id=f"main:{prompt_hash}",
                prompt_name="main",
                content_hash=prompt_hash,
                system_text="Extract laps.",
            )
            image = ImageFileEntity(
                id="image-1",
                file_hash=raw_hash,
                file_name="raw.png",
                current_name="raw.png",
                current_path=str(raw_path),
            )
            session.add(prompt)
            session.add(image)
            session.flush()

            run = ExtractionRunEntity(
                id="run-1",
                status="completed",
                backend="lmstudio",
                model="qwen",
                prompt_snapshot_id=prompt.id,
                prompt_name=prompt.prompt_name,
                prompt_hash=prompt.content_hash,
                total_inputs=1,
                to_process=1,
                processed=1,
                succeeded=1,
            )
            session.add(run)
            session.flush()

            runtime = ModelRuntimeSnapshotEntity(
                id="runtime-1",
                run_id=run.id,
                snapshot_kind="preflight",
                endpoint="http://localhost:1234",
                health_ok=True,
            )
            run_input = RunInputEntity(
                run_id=run.id,
                image_file_id=image.id,
                input_order=0,
                input_path=str(raw_path),
                file_name="raw.png",
                extension=".png",
                file_hash=image.file_hash,
                decision="process",
            )
            session.add(runtime)
            session.add(run_input)
            session.flush()
            result = ExtractionResultEntity(
                id="result-1",
                run_id=run.id,
                run_input_id=run_input.id,
                image_file_id=image.id,
                status="ok",
                prompt_snapshot_id=prompt.id,
            )
            session.add(result)
            session.flush()
            attempt = ExtractionAttemptEntity(
                id="attempt-1",
                extraction_result_id=result.id,
                run_id=run.id,
                image_file_id=image.id,
                runtime_snapshot_id=runtime.id,
                attempt_number=1,
                attempt_reason="initial",
                status="ok",
                accepted=True,
                raw_response='{"track":"Test"}',
                request_messages_json=[{"role": "user", "content": "[image redacted]"}],
                request_config_json={},
                request_image_format="png",
                request_image_mime_type="image/png",
                request_image_width=1920,
                request_image_height=1080,
                request_image_bytes=100,
            )
            attempt.request_hash = canonical_request_hash(
                request_messages_json=attempt.request_messages_json,
                request_config_json=attempt.request_config_json,
                prompt_snapshot_id=prompt.id,
                model=attempt.model,
                source_file_hash=image.file_hash,
                request_image_format=attempt.request_image_format,
                request_image_mime_type=attempt.request_image_mime_type,
                request_image_width=attempt.request_image_width,
                request_image_height=attempt.request_image_height,
                request_image_bytes=attempt.request_image_bytes,
            )
            session.add(attempt)
            session.flush()
            result.accepted_attempt_id = attempt.id
            result.attempt_count = 1
            session.add(result)
            session.commit()
            return {
                "run_id": run.id,
                "image_file_id": image.id,
                "result_id": result.id,
                "attempt_id": attempt.id,
                "run_input_id": run_input.id,
            }
    finally:
        engine.dispose()


def _report_by_key(db_path: Path):
    report = DbDoctorService().run(db_path)
    return report, {check.key: check for check in report.checks}
