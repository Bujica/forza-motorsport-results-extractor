from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sqlmodel import select

from ..db.models import (
    ExtractionAttemptEntity,
    ExtractionResultEntity,
    ExtractionRunEntity,
    LapRecordEntity,
    ModelArtifactEntity,
    ReviewCaseEntity,
)
from ..schemas import ExtractionRun, ImageFile
from ..db.repositories import ReferenceRepository
from .gui_read.artifact_reads import GuiArtifactReadQueries, _normalise_raw_response_roots
from .gui_read.context_reads import result_context_maps
from .gui_read.dashboard_reads import GuiDashboardReadQueries
from .gui_read.image_debug_reads import GuiImageDebugReadQueries, _parse_raw_json
from .gui_read.image_reads import GuiImageReadQueries
from .gui_read.lap_reads import GuiLapReadQueries
from .gui_read.review_reads import GuiReviewReadQueries
from .gui_read.run_reads import GuiRunReadQueries, _run_option
from .gui_read.session_provider import GuiReadSessionProvider
from .gui_read.types import (
    DashboardSummary,
    GuiExtractionAttempt,
    GuiExtractionResult,
    GuiImage,
    GuiImageDebugArtifact,
    GuiImageDebugAttempt,
    GuiImageDebugSummary,
    GuiImageDebugCase,
    GuiImageDebugDetail,
    GuiImageDebugExtraction,
    GuiImageDebugLap,
    GuiImageDebugReview,
    GuiImageDebugRuntime,
    GuiLap,
    GuiReviewCase,
    GuiRunOption,
)


class GuiReadService:
    """Read-only facade for GUI screens.

    SQL rows are the primary debug evidence. Registered artifact files can be
    read only when a caller explicitly provides allowed roots; no local debug
    directory is used as hidden runtime fallback state.
    """

    def __init__(self, database_file: Path, raw_response_roots: Sequence[Path] | None = None):
        self._session_provider = GuiReadSessionProvider(database_file)
        self._artifact_reads = GuiArtifactReadQueries(self._session_provider)
        self._dashboard_reads = GuiDashboardReadQueries(self._session_provider)
        self._image_reads = GuiImageReadQueries(self._session_provider)
        self._lap_reads = GuiLapReadQueries(self._session_provider)
        self._review_reads = GuiReviewReadQueries(self._session_provider)
        self._run_reads = GuiRunReadQueries(self._session_provider)
        self.database_file = self._session_provider.database_file
        self._raw_response_roots = _normalise_raw_response_roots(raw_response_roots)
        self._image_debug_reads = GuiImageDebugReadQueries(self._session_provider, self._raw_response_roots)

    def close(self) -> None:
        self._session_provider.close()

    def invalidate_schema_cache(self) -> None:
        self._session_provider.invalidate_schema_cache()

    def __enter__(self) -> GuiReadService:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def list_images(
        self,
        *,
        file_status: str | None = None,
        best_lap_status: str | None = None,
        inventory_filter: str | None = None,
        track: str | None = None,
        run_id: str | None = None,
        processing_status: str | None = None,
    ) -> list[GuiImage]:
        return self._image_reads.list_images(
            file_status=file_status,
            best_lap_status=best_lap_status,
            inventory_filter=inventory_filter,
            track=track,
            run_id=run_id,
            processing_status=processing_status,
        )
    def image_filter_values(
        self,
        *,
        file_status: str | None = None,
        best_lap_status: str | None = None,
        inventory_filter: str | None = None,
        track: str | None = None,
        run_id: str | None = None,
        processing_status: str | None = None,
    ) -> tuple[list[str], list[GuiRunOption]]:
        return self._image_reads.image_filter_values(
            file_status=file_status,
            best_lap_status=best_lap_status,
            inventory_filter=inventory_filter,
            track=track,
            run_id=run_id,
            processing_status=processing_status,
        )
    def get_image(self, image_file_id: str) -> ImageFile | None:
        return self._image_reads.get_image(image_file_id)
    def list_runs(self, *, limit: int = 50) -> list[ExtractionRun]:
        return self._run_reads.list_runs(limit=limit)

    def list_run_options(self, *, limit: int = 100) -> list[GuiRunOption]:
        return self._run_reads.list_run_options(limit=limit)

    def list_reference_tracks(self) -> list[str]:
        if not self._can_read():
            return []
        with self._session() as session:
            return ReferenceRepository(session).list_tracks()

    def get_run(self, run_id: str) -> ExtractionRun | None:
        return self._run_reads.get_run(run_id)

    def list_laps(
        self,
        *,
        image_file_id: str | None = None,
        run_id: str | None = None,
        track: str | None = None,
        race_class: str | None = None,
        driver: str | None = None,
        best_only: bool | None = None,
        dirty: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[GuiLap]:
        return self._lap_reads.list_laps(
            image_file_id=image_file_id,
            run_id=run_id,
            track=track,
            race_class=race_class,
            driver=driver,
            best_only=best_only,
            dirty=dirty,
            limit=limit,
            offset=offset,
        )

    def list_extraction_results(
        self,
        *,
        image_file_id: str | None = None,
        run_id: str | None = None,
        status: str | None = None,
        model: str | None = None,
        prompt_name: str | None = None,
    ) -> list[GuiExtractionResult]:
        if not self._can_read():
            return []
        with self._session() as session:
            query = select(ExtractionResultEntity).join(ExtractionRunEntity, ExtractionRunEntity.id == ExtractionResultEntity.run_id)
            if image_file_id is not None:
                query = query.where(ExtractionResultEntity.image_file_id == image_file_id)
            if run_id is not None:
                query = query.where(ExtractionResultEntity.run_id == run_id)
            if status is not None:
                query = query.where(ExtractionResultEntity.status == status)
            if model is not None:
                query = query.where(ExtractionResultEntity.model == model)
            if prompt_name is not None:
                query = query.where(ExtractionRunEntity.prompt_name == prompt_name)
            rows = session.exec(query.order_by(ExtractionResultEntity.created_at.desc())).all()
            runs, attempts, artifacts = result_context_maps(session, rows)
            return [
                self._extraction_result(row, runs.get(row.run_id), attempts.get(row.accepted_attempt_id), artifacts.get(row.id))
                for row in rows
            ]

    def list_extraction_attempts(self, *, image_file_id: str | None = None, extraction_result_id: str | None = None) -> list[GuiExtractionAttempt]:
        if not self._can_read():
            return []
        with self._session() as session:
            query = select(ExtractionAttemptEntity)
            if image_file_id is not None:
                query = query.where(ExtractionAttemptEntity.image_file_id == image_file_id)
            if extraction_result_id is not None:
                query = query.where(ExtractionAttemptEntity.extraction_result_id == extraction_result_id)
            rows = session.exec(query.order_by(ExtractionAttemptEntity.created_at.desc(), ExtractionAttemptEntity.attempt_number.asc())).all()
            return [self._extraction_attempt(row) for row in rows]

    def get_extraction_result(self, image_file_id: str, run_id: str | None = None) -> GuiExtractionResult | None:
        if not self._can_read():
            return None
        with self._session() as session:
            query = select(ExtractionResultEntity).where(ExtractionResultEntity.image_file_id == image_file_id)
            if run_id is not None:
                query = query.where(ExtractionResultEntity.run_id == run_id)
            row = session.exec(query.order_by(ExtractionResultEntity.created_at.desc())).first()
            if row is None:
                return None
            runs, attempts, artifacts = result_context_maps(session, [row])
            return self._extraction_result(row, runs.get(row.run_id), attempts.get(row.accepted_attempt_id), artifacts.get(row.id))

    def list_image_debug_cases(
        self,
        *,
        status: str | None = None,
        backend: str | None = None,
        model: str | None = None,
        prompt_name: str | None = None,
        run_id: str | None = None,
        limit: int = 500,
    ) -> list[GuiImageDebugCase]:
        return self._image_debug_reads.list_image_debug_cases(
            status=status,
            backend=backend,
            model=model,
            prompt_name=prompt_name,
            run_id=run_id,
            limit=limit,
        )

    def get_image_debug_case(self, image_file_id: str, *, selected_result_id: str | None = None) -> GuiImageDebugDetail | None:
        return self._image_debug_reads.get_image_debug_case(image_file_id, selected_result_id=selected_result_id)

    def get_image_debug_case_by_result(self, extraction_result_id: str) -> GuiImageDebugDetail | None:
        return self._image_debug_reads.get_image_debug_case_by_result(extraction_result_id)

    def read_registered_artifact_text(
        self,
        extraction_result_id: str,
        *,
        artifact_type: str = "raw_response",
        allowed_roots: Sequence[Path],
    ) -> str | None:
        """Explicitly read a registered artifact file inside caller-approved roots."""
        return self._artifact_reads.read_registered_artifact_text(
            extraction_result_id,
            artifact_type=artifact_type,
            allowed_roots=allowed_roots,
        )

    def list_review_queue(
        self,
        *,
        status: str | None = "open",
        reason: str | None = None,
        outcome: str | None = None,
        run_id: str | None = None,
        image_file_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[GuiReviewCase]:
        return self._review_reads.list_review_queue(
            status=status,
            reason=reason,
            outcome=outcome,
            run_id=run_id,
            image_file_id=image_file_id,
            limit=limit,
            offset=offset,
        )


    def dashboard_summary(self) -> DashboardSummary:
        return self._dashboard_reads.dashboard_summary()

    def _can_read(self) -> bool:
        return self._session_provider.can_read()

    def _get_engine(self):
        return self._session_provider.get_engine()

    def _session(self):
        return self._session_provider.session()

    def _extraction_result(
        self,
        row: ExtractionResultEntity,
        run: ExtractionRunEntity | None,
        attempt: ExtractionAttemptEntity | None,
        artifact: ModelArtifactEntity | None,
    ) -> GuiExtractionResult:
        raw_response = attempt.raw_response if attempt is not None else None
        return GuiExtractionResult(
            id=row.id,
            run_id=row.run_id,
            image_file_id=row.image_file_id,
            status=row.status,
            error_message=row.error_message,
            backend=run.backend if run is not None else None,
            model=row.model,
            prompt_name=run.prompt_name if run is not None else None,
            raw_response_artifact_path=artifact.file_path if artifact is not None else None,
            has_raw_response=bool(raw_response or artifact is not None),
            has_parsed_result=bool(attempt is not None and attempt.parsed_json is not None),
            raw_response=raw_response,
            raw_response_payload=_parse_raw_json(attempt.raw_response) if attempt is not None else None,
            parsed_result_payload=attempt.parsed_json if attempt is not None else None,
            created_at=row.created_at,
        )

    def _extraction_attempt(self, row: ExtractionAttemptEntity) -> GuiExtractionAttempt:
        return GuiExtractionAttempt(
            id=row.id,
            extraction_result_id=row.extraction_result_id,
            attempt_number=row.attempt_number,
            attempt_reason=row.attempt_reason,
            status=row.status,
            accepted=row.accepted,
            rejected_reason=row.rejected_reason,
            model=row.model,
            model_instance_id=row.model_instance_id,
            context_length=row.context_length,
            reasoning_mode=row.reasoning_mode,
            duration_ms=row.duration_ms,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            total_tokens=row.total_tokens,
            tokens_per_second=row.tokens_per_second,
            parse_error=row.parse_error,
            validation_status=row.validation_status,
            validation_issues_json=row.validation_issues_json,
            created_at=row.created_at,
        )
