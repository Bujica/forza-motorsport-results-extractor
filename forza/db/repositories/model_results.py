from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func
from sqlmodel import Session, select

from ..models import ExtractionAttemptEntity, ExtractionResultEntity, ExtractionRunEntity
from ...schemas import ExtractionResult, ModelExtractionAttempt
from .run_inputs import ensure_process_run_input


class ExtractionResultRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_result(
        self,
        result: ExtractionResult,
        *,
        run_id: str,
        image_file_id: str,
        run_input_id: int | None = None,
    ) -> ExtractionResultEntity:
        if run_input_id is None:
            run_input_id = ensure_process_run_input(
                self.session,
                result,
                run_id=run_id,
                image_file_id=image_file_id,
            )
        existing = self.session.exec(
            select(ExtractionResultEntity).where(
                ExtractionResultEntity.run_id == run_id,
                ExtractionResultEntity.image_file_id == image_file_id,
            )
        ).first()
        entity = existing or ExtractionResultEntity(
            id=uuid4().hex,
            run_id=run_id,
            run_input_id=run_input_id,
            image_file_id=image_file_id,
            status=str(result.status),
        )
        run = self.session.get(ExtractionRunEntity, run_id)
        entity.run_input_id = run_input_id
        entity.status = str(result.status)
        entity.error_message = result.error
        entity.error_type = _result_error_type(result)
        entity.model = result.model_name or (run.model if run is not None else None)
        entity.prompt_snapshot_id = run.prompt_snapshot_id if run is not None else None
        stats = result.model_response_stats
        entity.duration_ms = stats.duration_ms if stats is not None else None
        entity.input_tokens = stats.input_tokens if stats is not None else None
        entity.output_tokens = stats.output_tokens if stats is not None else None
        entity.total_tokens = stats.total_tokens if stats is not None else None
        entity.reasoning_tokens = stats.reasoning_output_tokens if stats is not None else None
        entity.tokens_per_second = stats.tokens_per_second if stats is not None else None
        entity.time_to_first_token_s = stats.time_to_first_token_seconds if stats is not None else None
        entity.model_load_time_s = stats.model_load_time_seconds if stats is not None else None
        if result.model_request is not None:
            req = result.model_request
            entity.request_image_format = req.request_image_format
            entity.request_image_mime_type = req.request_image_mime_type
            entity.request_image_width = req.request_image_width_px
            entity.request_image_height = req.request_image_height_px
            entity.request_image_bytes = req.request_image_bytes
        self.session.add(entity)
        self.session.flush()
        accepted_attempt_id, attempt_count = self._append_attempts(
            result,
            extraction_result_id=entity.id,
            run_id=run_id,
            image_file_id=image_file_id,
        )
        if str(result.status) == "ok" and accepted_attempt_id is None:
            raise ValueError(
                "Successful extraction result requires a persisted accepted real attempt"
            )
        entity.accepted_attempt_id = accepted_attempt_id
        entity.attempt_count = attempt_count
        accepted = self.session.get(ExtractionAttemptEntity, accepted_attempt_id) if accepted_attempt_id else None
        if accepted is not None:
            entity.model_instance_id = accepted.model_instance_id
        entity.updated_at = datetime.now(timezone.utc)
        self.session.add(entity)
        return entity

    def begin_result(
        self,
        *,
        run_id: str,
        run_input_id: int,
        image_file_id: str,
        model: str | None = None,
        prompt_snapshot_id: str | None = None,
    ) -> ExtractionResultEntity:
        existing = self.session.exec(
            select(ExtractionResultEntity).where(
                ExtractionResultEntity.run_id == run_id,
                ExtractionResultEntity.image_file_id == image_file_id,
            )
        ).first()
        if existing is not None:
            return existing
        entity = ExtractionResultEntity(
            id=uuid4().hex,
            run_id=run_id,
            run_input_id=run_input_id,
            image_file_id=image_file_id,
            status="running",
            model=model,
            prompt_snapshot_id=prompt_snapshot_id,
        )
        self.session.add(entity)
        self.session.flush()
        return entity

    def append_attempt(
        self,
        attempt: ModelExtractionAttempt,
        *,
        extraction_result_id: str,
        run_id: str,
        image_file_id: str,
    ) -> ExtractionAttemptEntity:
        result = self.session.get(ExtractionResultEntity, extraction_result_id)
        if result is None:
            raise ValueError(
                f"extraction_result_id does not exist for model attempt: {extraction_result_id}"
            )
        existing = self.session.exec(
            select(ExtractionAttemptEntity).where(
                ExtractionAttemptEntity.extraction_result_id == extraction_result_id,
                ExtractionAttemptEntity.attempt_number == attempt.attempt_number,
            )
        ).first()
        if existing is not None:
            return existing
        entity = _attempt_entity(
            attempt,
            extraction_result_id=extraction_result_id,
            run_id=run_id,
            image_file_id=image_file_id,
        )
        self.session.add(entity)
        self.session.flush()
        result.attempt_count = self._attempt_count(extraction_result_id)
        if entity.accepted:
            result.accepted_attempt_id = entity.id
        result.updated_at = datetime.now(timezone.utc)
        self.session.add(result)
        return entity

    def by_id(self, result_id: str) -> ExtractionResultEntity | None:
        return self.session.get(ExtractionResultEntity, result_id)

    def list_by_image(self, image_file_id: str) -> list[ExtractionResultEntity]:
        return list(
            self.session.exec(
                select(ExtractionResultEntity)
                .where(ExtractionResultEntity.image_file_id == image_file_id)
                .order_by(ExtractionResultEntity.created_at.desc())
            )
        )

    def _append_attempts(
        self,
        result: ExtractionResult,
        *,
        extraction_result_id: str,
        run_id: str,
        image_file_id: str,
    ) -> tuple[str | None, int]:
        attempts = list(result.model_attempts)
        for attempt in attempts:
            self.append_attempt(
                attempt,
                extraction_result_id=extraction_result_id,
                run_id=run_id,
                image_file_id=image_file_id,
            )
        self.session.flush()
        rows = self.session.exec(
            select(ExtractionAttemptEntity).where(
                ExtractionAttemptEntity.extraction_result_id == extraction_result_id
            )
        ).all()
        accepted = next((row for row in rows if row.accepted), None)
        return (accepted.id if accepted is not None else None), len(rows)

    def _attempt_count(self, extraction_result_id: str) -> int:
        return int(
            self.session.exec(
                select(func.count())
                .select_from(ExtractionAttemptEntity)
                .where(ExtractionAttemptEntity.extraction_result_id == extraction_result_id)
            ).one()
        )


def _attempt_entity(
    attempt: ModelExtractionAttempt,
    *,
    extraction_result_id: str,
    run_id: str,
    image_file_id: str,
) -> ExtractionAttemptEntity:
    return ExtractionAttemptEntity(
        id=uuid4().hex,
        extraction_result_id=extraction_result_id,
        run_id=run_id,
        image_file_id=image_file_id,
        runtime_snapshot_id=attempt.runtime_snapshot_id,
        attempt_number=attempt.attempt_number,
        attempt_reason=attempt.attempt_reason,
        status=attempt.status,
        accepted=attempt.accepted,
        rejected_reason=attempt.rejected_reason,
        endpoint_url=attempt.endpoint_url,
        model=attempt.model,
        model_instance_id=attempt.model_instance_id,
        request_image_format=attempt.request_image_format,
        request_image_mime_type=attempt.request_image_mime_type,
        request_image_width=attempt.request_image_width_px,
        request_image_height=attempt.request_image_height_px,
        request_image_bytes=attempt.request_image_bytes,
        context_length=attempt.context_length,
        reasoning_mode=attempt.reasoning_mode,
        request_config_json=attempt.request_config_json,
        request_messages_json=attempt.request_messages_json,
        request_hash=attempt.request_hash,
        retry_instruction_text=attempt.retry_instruction_text,
        model_load_config_json=attempt.model_load_config_json,
        duration_ms=attempt.duration_ms,
        http_status=attempt.http_status,
        error_code=attempt.error_code,
        error_message=attempt.error_message,
        input_tokens=attempt.input_tokens,
        output_tokens=attempt.output_tokens,
        total_tokens=attempt.total_tokens,
        reasoning_tokens=attempt.reasoning_output_tokens,
        tokens_per_second=attempt.tokens_per_second,
        time_to_first_token_s=attempt.time_to_first_token_seconds,
        model_load_time_s=attempt.model_load_time_seconds,
        raw_response=attempt.raw_response,
        parsed_json=attempt.parsed_json,
        parse_error=attempt.parse_error,
        validation_status=attempt.validation_status,
        validation_issues_json=attempt.validation_issues_json,
        response_stats_json=attempt.response_stats_json,
    )


def _result_error_type(result: ExtractionResult) -> str | None:
    if str(result.status) == "ok":
        return None
    if str(result.status) == "cancelled":
        return "cancelled"
    if result.model_attempts:
        rejected = result.model_attempts[-1].rejected_reason
        if rejected == "transport_error":
            return "transport_error"
        if rejected in {"parse_error", "validation_error"}:
            return rejected
    if result.error:
        return "extraction_error"
    return None
