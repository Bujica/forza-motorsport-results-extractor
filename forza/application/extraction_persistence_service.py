from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

from sqlmodel import Session, select

from ..db.models import (
    ExtractionAttemptEntity,
    ExtractionRunEntity,
    ModelArtifactEntity,
    ModelRuntimeSnapshotEntity,
    RunInputEntity,
)
from ..db.repositories import ExtractionResultRepository, LapRepository, ImageFileRepository
from ..schemas import ExtractionResult, ModelExtractionAttempt
from .db_session_provider import DbSessionProvider


@dataclass(frozen=True)
class PreparedExtraction:
    extraction_result_id: str
    image_file_id: str
    run_input_id: int
    prompt_snapshot_id: str | None
    runtime_snapshot_id: str | None


class ExtractionPersistenceService:
    """Owns extraction persistence helpers."""

    def __init__(self, session_provider: DbSessionProvider):
        self._session_provider = session_provider

    def prepare_extraction_result(
        self,
        *,
        run_id: str,
        file_hash: str,
        path: Path,
    ) -> PreparedExtraction:
        """Insert the per-image running row before encoding or calling chat."""
        with Session(self._session_provider.engine_for_db()) as session:
            images = ImageFileRepository(session)
            image = images.by_current_path(path)
            if image is not None and image.file_hash != file_hash:
                image = None
            if image is None:
                image = images.upsert(
                    file_hash=file_hash,
                    file_name=path.name,
                    current_path=path,
                    current_name=path.name,
                )
                session.flush()
            run_input = session.exec(
                select(RunInputEntity).where(
                    RunInputEntity.run_id == run_id,
                    RunInputEntity.image_file_id == image.id,
                    RunInputEntity.decision == "process",
                )
            ).first()
            if run_input is None or run_input.id is None:
                raise RuntimeError(
                    f"No process run_input for run={run_id} file_hash={file_hash}"
                )
            run = session.get(ExtractionRunEntity, run_id)
            if run is None:
                raise RuntimeError(f"Run not found: {run_id}")
            result = ExtractionResultRepository(session).begin_result(
                run_id=run_id,
                run_input_id=run_input.id,
                image_file_id=image.id,
                model=run.model,
                prompt_snapshot_id=run.prompt_snapshot_id,
            )
            snapshot = session.exec(
                select(ModelRuntimeSnapshotEntity)
                .where(
                    ModelRuntimeSnapshotEntity.run_id == run_id,
                    ModelRuntimeSnapshotEntity.snapshot_kind == "preflight",
                )
                .order_by(ModelRuntimeSnapshotEntity.captured_at.desc())
            ).first()
            session.commit()
            return PreparedExtraction(
                extraction_result_id=result.id,
                image_file_id=image.id,
                run_input_id=run_input.id,
                prompt_snapshot_id=run.prompt_snapshot_id,
                runtime_snapshot_id=snapshot.id if snapshot is not None else None,
            )


    def record_extraction_attempt(
        self,
        *,
        prepared: PreparedExtraction,
        attempt: ModelExtractionAttempt,
        run_id: str,
    ) -> str:
        """Append one completed real chat attempt and its file artifact."""
        with Session(self._session_provider.engine_for_db()) as session:
            entity = ExtractionResultRepository(session).append_attempt(
                attempt,
                extraction_result_id=prepared.extraction_result_id,
                run_id=run_id,
                image_file_id=prepared.image_file_id,
            )
            if attempt.artifact_path:
                register_model_artifact(
                    session,
                    path=Path(attempt.artifact_path),
                    artifact_type=attempt.artifact_type or "debug_json",
                    run_id=run_id,
                    image_file_id=prepared.image_file_id,
                    extraction_result_id=prepared.extraction_result_id,
                    attempt_id=entity.id,
                    is_canonical=attempt.artifact_is_canonical,
                )
            session.commit()
            return entity.id


    def upsert_image_and_laps(
        self,
        result: ExtractionResult,
        *,
        run_id: str,
        gamertag: str | None = None,
    ) -> int:
        del gamertag  # Kept for DatabaseService compatibility; lap persistence derives the driver from result rows.
        with Session(self._session_provider.engine_for_db()) as session:
            images = ImageFileRepository(session)
            model_results = ExtractionResultRepository(session)
            laps = LapRepository(session)
            image = images.upsert(
                file_hash=result.file_hash,
                file_name=result.source_file,
                current_path=result.current_path,
                current_name=Path(result.current_path).name if result.current_path else result.source_file,
                semantic_name=result.semantic_name,
            )
            extraction_result = model_results.add_result(
                result,
                run_id=run_id,
                image_file_id=image.id,
            )
            for attempt in result.model_attempts:
                if not attempt.artifact_path:
                    continue
                attempt_row = session.exec(
                    select(ExtractionAttemptEntity).where(
                        ExtractionAttemptEntity.extraction_result_id == extraction_result.id,
                        ExtractionAttemptEntity.attempt_number == attempt.attempt_number,
                    )
                ).first()
                register_model_artifact(
                    session,
                    path=Path(attempt.artifact_path),
                    artifact_type=attempt.artifact_type or "debug_json",
                    run_id=run_id,
                    image_file_id=image.id,
                    extraction_result_id=extraction_result.id,
                    attempt_id=attempt_row.id if attempt_row is not None else None,
                    is_canonical=attempt.artifact_is_canonical,
                )
            self._register_raw_artifact(
                session,
                result=result,
                run_id=run_id,
                image_file_id=image.id,
                extraction_result_id=extraction_result.id,
                attempt_id=extraction_result.accepted_attempt_id,
            )
            persisted = replace(
                result,
                image_file_id=image.id,
                run_id=run_id,
                extraction_result_id=extraction_result.id,
            )
            if persisted.session is None:
                session.commit()
                return 0
            entities = laps.add_result(
                persisted,
                run_id=run_id,
                image_file_id=image.id,
                extraction_result_id=extraction_result.id,
            )
            session.commit()
            return len(entities)

    def _register_raw_artifact(
        self,
        session: Session,
        *,
        result: ExtractionResult,
        run_id: str,
        image_file_id: str,
        extraction_result_id: str,
        attempt_id: str | None,
    ) -> None:
        if not result.raw_response_artifact_path:
            return
        path = Path(result.raw_response_artifact_path)
        register_model_artifact(
            session,
            path=path,
            artifact_type="raw_response",
            run_id=run_id,
            image_file_id=image_file_id,
            extraction_result_id=extraction_result_id,
            attempt_id=attempt_id,
            is_canonical=True,
        )


def register_model_artifact(
    session: Session,
    *,
    path: Path,
    artifact_type: str,
    run_id: str,
    image_file_id: str,
    extraction_result_id: str,
    attempt_id: str | None,
    is_canonical: bool,
) -> ModelArtifactEntity | None:
    if not path.exists() or not path.is_file():
        return None
    data = path.read_bytes()
    existing = session.exec(
        select(ModelArtifactEntity).where(
            ModelArtifactEntity.extraction_result_id == extraction_result_id,
            ModelArtifactEntity.artifact_type == artifact_type,
            ModelArtifactEntity.file_path == str(path),
        )
    ).first()
    digest = hashlib.sha256(data).hexdigest()
    if existing is not None:
        expected_linkage = (
            existing.run_id == run_id
            and existing.image_file_id == image_file_id
            and existing.extraction_result_id == extraction_result_id
            and existing.attempt_id == attempt_id
            and existing.is_canonical == is_canonical
        )
        if (
            existing.sha256 != digest
            or existing.size_bytes != len(data)
            or not expected_linkage
        ):
            raise RuntimeError(
                "Registered model artifact is immutable and no longer matches "
                f"its persisted evidence: {path}"
            )
        return existing
    artifact = ModelArtifactEntity(
        id=uuid4().hex,
        run_id=run_id,
        image_file_id=image_file_id,
        extraction_result_id=extraction_result_id,
        attempt_id=attempt_id,
        artifact_type=artifact_type,
        file_path=str(path),
        relative_path=str(path),
        sha256=digest,
        size_bytes=len(data),
        media_type="application/json",
        is_canonical=is_canonical,
    )
    session.add(artifact)
    return artifact


__all__ = ["ExtractionPersistenceService", "PreparedExtraction"]
