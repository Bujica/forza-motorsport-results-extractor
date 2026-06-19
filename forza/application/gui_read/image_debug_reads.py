from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from ...db.models import (
    ExtractionAttemptEntity,
    ExtractionResultEntity,
    ExtractionRunEntity,
    ImageFileEntity,
    LapRecordEntity,
    ModelArtifactEntity,
    ModelRuntimeSnapshotEntity,
    ReviewCaseEntity,
)
from .artifact_reads import _read_text_file
from .image_reads import _latest_processing_statuses
from .run_reads import _run_option
from .session_provider import GuiReadSessionProvider
from .types import (
    GuiImage,
    GuiImageDebugArtifact,
    GuiImageDebugAttempt,
    GuiImageDebugCase,
    GuiImageDebugDetail,
    GuiImageDebugExtraction,
    GuiImageDebugLap,
    GuiImageDebugReview,
    GuiImageDebugRuntime,
)


class GuiImageDebugReadQueries:
    """Image-centric diagnostics read model for the GUI Image Debug tab."""

    def __init__(self, session_provider: GuiReadSessionProvider, raw_response_roots: Sequence[Path]):
        self._session_provider = session_provider
        self._raw_response_roots = tuple(raw_response_roots)

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
        if not self._session_provider.can_read():
            return []
        with self._session_provider.session() as session:
            rows = session.exec(select(ImageFileEntity).order_by(ImageFileEntity.updated_at.desc()).limit(limit)).all()
            cases = _cases_for_images(session, rows)
        return [
            case
            for case in cases
            if _matches_case(case, status=status, backend=backend, model=model, prompt_name=prompt_name, run_id=run_id)
        ]

    def get_image_debug_case(self, image_file_id: str, *, selected_result_id: str | None = None) -> GuiImageDebugDetail | None:
        if not self._session_provider.can_read():
            return None
        with self._session_provider.session() as session:
            image = session.get(ImageFileEntity, image_file_id)
            if image is None:
                return None
            return _detail_for_image(session, image, self._raw_response_roots, selected_result_id=selected_result_id)

    def get_image_debug_case_by_result(self, extraction_result_id: str) -> GuiImageDebugDetail | None:
        if not self._session_provider.can_read():
            return None
        with self._session_provider.session() as session:
            result = session.get(ExtractionResultEntity, extraction_result_id)
            if result is None:
                return None
            image = session.get(ImageFileEntity, result.image_file_id)
            if image is None:
                return None
            return _detail_for_image(session, image, self._raw_response_roots, selected_result_id=extraction_result_id)


def _matches_case(
    case: GuiImageDebugCase,
    *,
    status: str | None,
    backend: str | None,
    model: str | None,
    prompt_name: str | None,
    run_id: str | None,
) -> bool:
    for value, current in (
        (status, case.latest_result_status),
        (backend, case.backend),
        (model, case.model),
        (prompt_name, case.prompt_name),
        (run_id, case.run_id),
    ):
        if value not in (None, "", "all") and value != current:
            return False
    return True


def _cases_for_images(session: Session, images: list[ImageFileEntity]) -> list[GuiImageDebugCase]:
    image_ids = [row.id for row in images]
    if not image_ids:
        return []
    results_by_image = _results_by_image(session, image_ids)
    run_ids = {result.run_id for results in results_by_image.values() for result in results}
    runs = _runs_by_id(session, run_ids)
    processing = _latest_processing_statuses(session, image_ids)
    lap_counts = _count_by_image(session, LapRecordEntity.image_file_id, image_ids)
    review_counts = _count_by_image(session, ReviewCaseEntity.image_file_id, image_ids)
    artifact_counts = _count_by_image(session, ModelArtifactEntity.image_file_id, image_ids)
    return [
        _case_for_image(
            image,
            results_by_image.get(image.id, []),
            runs,
            processing.get(image.id, "unprocessed"),
            lap_counts.get(image.id, 0),
            review_counts.get(image.id, 0),
            artifact_counts.get(image.id, 0),
        )
        for image in images
    ]


def _case_for_image(
    image: ImageFileEntity,
    results: list[ExtractionResultEntity],
    runs: dict[str, ExtractionRunEntity],
    processing_status: str,
    lap_count: int,
    review_count: int,
    artifact_count: int,
) -> GuiImageDebugCase:
    latest = results[0] if results else None
    run = runs.get(latest.run_id) if latest is not None else None
    return GuiImageDebugCase(
        image_file_id=image.id,
        image_name=image.current_name or image.semantic_name or image.id,
        race_date=image.race_date or image.race_datetime,
        file_status=image.file_status,
        processing_status=processing_status,
        best_lap_status=image.best_lap_status,
        latest_result_id=latest.id if latest is not None else None,
        latest_result_status=latest.status if latest is not None else None,
        run_id=latest.run_id if latest is not None else None,
        run_label=_run_option(run).label if run is not None else (latest.run_id if latest is not None else None),
        backend=run.backend if run is not None else None,
        model=latest.model if latest is not None else None,
        prompt_name=run.prompt_name if run is not None else None,
        attempt_count=sum(result.attempt_count for result in results),
        lap_count=lap_count,
        review_count=review_count,
        artifact_count=artifact_count,
        created_at=latest.created_at if latest is not None else image.created_at,
    )


def _detail_for_image(
    session: Session,
    image: ImageFileEntity,
    raw_response_roots: Sequence[Path],
    *,
    selected_result_id: str | None,
) -> GuiImageDebugDetail:
    cases = _cases_for_images(session, [image])
    results = _results_by_image(session, [image.id]).get(image.id, [])
    selected = _selected_result(results, selected_result_id)
    selected_result_id = selected.id if selected is not None else None
    run_ids = {result.run_id for result in results}
    runs = _runs_by_id(session, run_ids)
    attempts = _attempts_for_result(session, selected_result_id)
    selected_attempt = _accepted_or_latest_attempt(attempts)
    artifacts = _artifacts_for_image(session, image.id, selected_result_id)
    raw_artifact = _canonical_raw_artifact(artifacts, selected_attempt.id if selected_attempt is not None else None, selected_result_id)
    runtime = _runtime_for(session, run_ids, attempts)
    laps = _laps_for_image(session, image.id)
    reviews = _reviews_for_image(session, image.id)
    raw_response = selected_attempt.raw_response if selected_attempt is not None else None
    if not raw_response and raw_artifact is not None:
        raw_response = _read_text_file(raw_artifact.file_path, raw_response_roots)
    return GuiImageDebugDetail(
        image=_gui_image(image, _latest_processing_statuses(session, [image.id]).get(image.id, "unprocessed")),
        cases=cases,
        results=[_debug_extraction(result, runs.get(result.run_id)) for result in results],
        selected_result_id=selected_result_id,
        attempts=[_debug_attempt(row) for row in attempts],
        artifacts=[_debug_artifact(row) for row in artifacts],
        runtime_snapshots=[_debug_runtime(row) for row in runtime],
        laps=[_debug_lap(row) for row in laps],
        reviews=[_debug_review(row) for row in reviews],
        raw_response=raw_response,
        raw_response_payload=_parse_raw_json(raw_response),
        parsed_result_payload=selected_attempt.parsed_json if selected_attempt is not None else None,
        timeline=_timeline(image, results, attempts, laps, reviews, artifacts),
    )


def _results_by_image(session: Session, image_ids: list[str]) -> dict[str, list[ExtractionResultEntity]]:
    rows = session.exec(
        select(ExtractionResultEntity)
        .where(ExtractionResultEntity.image_file_id.in_(image_ids))
        .order_by(ExtractionResultEntity.created_at.desc(), ExtractionResultEntity.id.desc())
    ).all()
    grouped: dict[str, list[ExtractionResultEntity]] = {image_id: [] for image_id in image_ids}
    for row in rows:
        grouped.setdefault(row.image_file_id, []).append(row)
    return grouped


def _runs_by_id(session: Session, run_ids) -> dict[str, ExtractionRunEntity]:
    ids = {run_id for run_id in run_ids if run_id}
    if not ids:
        return {}
    return {row.id: row for row in session.exec(select(ExtractionRunEntity).where(ExtractionRunEntity.id.in_(ids))).all()}


def _count_by_image(session: Session, column, image_ids: list[str]) -> dict[str, int]:
    rows = session.exec(select(column, func.count()).where(column.in_(image_ids)).group_by(column)).all()
    return {str(image_id): int(count) for image_id, count in rows if image_id}


def _selected_result(results: list[ExtractionResultEntity], selected_result_id: str | None) -> ExtractionResultEntity | None:
    if selected_result_id:
        for result in results:
            if result.id == selected_result_id:
                return result
    return results[0] if results else None


def _attempts_for_result(session: Session, extraction_result_id: str | None) -> list[ExtractionAttemptEntity]:
    if not extraction_result_id:
        return []
    return session.exec(
        select(ExtractionAttemptEntity)
        .where(ExtractionAttemptEntity.extraction_result_id == extraction_result_id)
        .order_by(ExtractionAttemptEntity.attempt_number.asc())
    ).all()


def _accepted_or_latest_attempt(attempts: list[ExtractionAttemptEntity]) -> ExtractionAttemptEntity | None:
    for attempt in attempts:
        if attempt.accepted:
            return attempt
    return attempts[-1] if attempts else None


def _artifacts_for_image(session: Session, image_file_id: str, selected_result_id: str | None) -> list[ModelArtifactEntity]:
    query = select(ModelArtifactEntity).where(ModelArtifactEntity.image_file_id == image_file_id)
    if selected_result_id:
        query = query.where(
            (ModelArtifactEntity.extraction_result_id == selected_result_id)
            | (ModelArtifactEntity.extraction_result_id.is_(None))
        )
    return session.exec(query.order_by(ModelArtifactEntity.created_at.desc())).all()


def _canonical_raw_artifact(
    artifacts: list[ModelArtifactEntity], attempt_id: str | None, extraction_result_id: str | None
) -> ModelArtifactEntity | None:
    for artifact in artifacts:
        if artifact.artifact_type == "raw_response" and artifact.is_canonical and artifact.attempt_id == attempt_id:
            return artifact
    for artifact in artifacts:
        if artifact.artifact_type == "raw_response" and artifact.is_canonical and artifact.extraction_result_id == extraction_result_id:
            return artifact
    return None


def _runtime_for(session: Session, run_ids, attempts: list[ExtractionAttemptEntity]) -> list[ModelRuntimeSnapshotEntity]:
    runtime_ids = {attempt.runtime_snapshot_id for attempt in attempts if attempt.runtime_snapshot_id}
    rows: list[ModelRuntimeSnapshotEntity] = []
    if runtime_ids:
        rows.extend(session.exec(select(ModelRuntimeSnapshotEntity).where(ModelRuntimeSnapshotEntity.id.in_(runtime_ids))).all())
    run_id_set = {run_id for run_id in run_ids if run_id}
    if run_id_set:
        existing_ids = {row.id for row in rows}
        rows.extend(
            row
            for row in session.exec(
                select(ModelRuntimeSnapshotEntity)
                .where(ModelRuntimeSnapshotEntity.run_id.in_(run_id_set))
                .order_by(ModelRuntimeSnapshotEntity.captured_at.desc())
            ).all()
            if row.id not in existing_ids
        )
    return rows


def _laps_for_image(session: Session, image_file_id: str) -> list[LapRecordEntity]:
    return session.exec(
        select(LapRecordEntity)
        .where(LapRecordEntity.image_file_id == image_file_id)
        .order_by(LapRecordEntity.run_id.desc(), LapRecordEntity.lap_index.asc())
    ).all()


def _reviews_for_image(session: Session, image_file_id: str) -> list[ReviewCaseEntity]:
    return session.exec(
        select(ReviewCaseEntity)
        .where(ReviewCaseEntity.image_file_id == image_file_id)
        .order_by(ReviewCaseEntity.created_at.desc())
    ).all()


def _gui_image(image: ImageFileEntity, processing_status: str) -> GuiImage:
    return GuiImage(
        id=image.id,
        file_hash=image.file_hash,
        duplicate_of_image_file_id=image.duplicate_of_image_file_id,
        current_name=image.current_name,
        semantic_name=image.semantic_name,
        current_path=image.current_path,
        file_status=image.file_status,
        processing_status=processing_status,
        best_lap_status=image.best_lap_status,
        file_size_bytes=image.size_bytes,
        image_format=image.image_format,
        mime_type=image.mime_type,
        width_px=image.width_px,
        height_px=image.height_px,
        bit_depth=image.bit_depth,
        color_mode=image.color_mode,
        file_modified_at=image.file_modified_at,
        race_datetime=image.race_datetime,
        race_date=image.race_date,
        race_datetime_source=image.race_datetime_source,
        image_metadata_json=dict(image.image_metadata_json or {}),
    )


def _debug_extraction(row: ExtractionResultEntity, run: ExtractionRunEntity | None) -> GuiImageDebugExtraction:
    return GuiImageDebugExtraction(
        id=row.id,
        run_id=row.run_id,
        run_label=_run_option(run).label if run is not None else row.run_id,
        status=row.status,
        backend=run.backend if run is not None else None,
        model=row.model,
        prompt_name=run.prompt_name if run is not None else None,
        accepted_attempt_id=row.accepted_attempt_id,
        attempt_count=row.attempt_count,
        duration_ms=row.duration_ms,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        total_tokens=row.total_tokens,
        error_type=row.error_type,
        error_message=row.error_message,
        request_image_format=row.request_image_format,
        request_image_mime_type=row.request_image_mime_type,
        request_image_width=row.request_image_width,
        request_image_height=row.request_image_height,
        request_image_bytes=row.request_image_bytes,
        created_at=row.created_at,
    )


def _debug_attempt(row: ExtractionAttemptEntity) -> GuiImageDebugAttempt:
    return GuiImageDebugAttempt(
        id=row.id,
        extraction_result_id=row.extraction_result_id,
        runtime_snapshot_id=row.runtime_snapshot_id,
        attempt_number=row.attempt_number,
        attempt_reason=row.attempt_reason,
        status=row.status,
        accepted=row.accepted,
        rejected_reason=row.rejected_reason,
        http_status=row.http_status,
        error_code=row.error_code,
        error_message=row.error_message,
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
        validation_issues_json=list(row.validation_issues_json or []),
        request_config_json=row.request_config_json,
        request_messages_json=row.request_messages_json,
        response_stats_json=row.response_stats_json,
        model_load_config_json=row.model_load_config_json,
        created_at=row.created_at,
    )


def _debug_artifact(row: ModelArtifactEntity) -> GuiImageDebugArtifact:
    return GuiImageDebugArtifact(
        id=row.id,
        artifact_type=row.artifact_type,
        extraction_result_id=row.extraction_result_id,
        attempt_id=row.attempt_id,
        file_path=row.file_path,
        relative_path=row.relative_path,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        media_type=row.media_type,
        is_canonical=row.is_canonical,
        created_at=row.created_at,
    )


def _debug_runtime(row: ModelRuntimeSnapshotEntity) -> GuiImageDebugRuntime:
    return GuiImageDebugRuntime(
        id=row.id,
        run_id=row.run_id,
        snapshot_kind=row.snapshot_kind,
        endpoint=row.endpoint,
        configured_model=row.configured_model,
        matched_model=row.matched_model,
        loaded_model=row.loaded_model,
        instance_id=row.instance_id,
        display_name=row.display_name,
        publisher=row.publisher,
        architecture=row.architecture,
        format=row.format,
        params_string=row.params_string,
        quantization=row.quantization,
        selected_variant=row.selected_variant,
        size_bytes=row.size_bytes,
        max_context_length=row.max_context_length,
        capabilities_json=row.capabilities_json,
        desired_load_config_json=row.desired_load_config_json,
        effective_load_config_json=row.effective_load_config_json,
        load_time_seconds=row.load_time_seconds,
        health_ok=row.health_ok,
        health_message=row.health_message,
        model_matches_config=row.model_matches_config,
        captured_at=row.captured_at,
    )


def _debug_lap(row: LapRecordEntity) -> GuiImageDebugLap:
    return GuiImageDebugLap(
        id=row.id,
        extraction_result_id=row.extraction_result_id,
        run_id=row.run_id,
        lap_index=row.lap_index,
        track=row.track,
        race_class=row.race_class,
        driver=row.driver,
        car=row.car,
        best_lap=row.best_lap,
        dirty=row.dirty,
        is_best_lap=row.is_best_lap,
    )


def _debug_review(row: ReviewCaseEntity) -> GuiImageDebugReview:
    return GuiImageDebugReview(
        id=row.id,
        case_number=row.case_number,
        extraction_result_id=row.extraction_result_id,
        lap_record_id=row.lap_record_id,
        status=row.status,
        reason=row.reason,
        outcome=row.outcome,
        trigger=row.trigger,
        decision_field=row.decision_field,
        model_value=row.model_value,
        corrected_value=row.corrected_value,
        current_track=row.track,
        current_race_class=row.race_class,
        current_best_lap=row.best_lap,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


def _timeline(
    image: ImageFileEntity,
    results: list[ExtractionResultEntity],
    attempts: list[ExtractionAttemptEntity],
    laps: list[LapRecordEntity],
    reviews: list[ReviewCaseEntity],
    artifacts: list[ModelArtifactEntity],
) -> list[str]:
    events: list[tuple[str, str]] = []
    events.append((str(image.created_at), f"image registered · {image.current_name or image.id}"))
    if image.first_seen_at:
        events.append((str(image.first_seen_at), "image first seen"))
    for result in results:
        events.append((str(result.created_at), f"result {result.status} · {result.id}"))
    for attempt in attempts:
        suffix = "accepted" if attempt.accepted else attempt.status
        events.append((str(attempt.created_at), f"attempt #{attempt.attempt_number} · {suffix}"))
    for lap in laps:
        events.append((str(getattr(lap, "created_at", "")), f"lap #{lap.lap_index} · {lap.track} · {lap.best_lap}"))
    for review in reviews:
        events.append((str(review.created_at), f"review #{review.case_number} · {review.status} · {review.reason}"))
    for artifact in artifacts:
        events.append((str(artifact.created_at), f"artifact {artifact.artifact_type} · {artifact.relative_path or artifact.file_path}"))
    return [message for _stamp, message in sorted(events, key=lambda item: item[0])]


def _parse_raw_json(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None
