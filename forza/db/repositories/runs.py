from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
import json

from sqlalchemy import func
from sqlmodel import Session, select

from ..models import ExtractionRunEntity, ReviewCaseEntity
from ...schemas import ExtractionRun, RunStatus

_VALID_RUN_STATUSES = {status.value for status in RunStatus}
_RESULT_STATUSES = {"ok", "error"}
_FLAT_METRIC_KEYS = {
    "processed",
    "succeeded",
    "failed",
    "review_case_count",
    "total_inputs",
    "to_process",
    "skipped",
    "duplicate_count",
}
_NON_EXTRA_METRIC_KEYS = _FLAT_METRIC_KEYS | {"operational_error_message"}


def _run_config_loads(value: str | None) -> dict[str, object]:
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return value if isinstance(value, dict) else {}


def _run_config_dumps(value: dict | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _status_value(status: RunStatus | str) -> str:
    value = status.value if isinstance(status, RunStatus) else str(status)
    if value in _RESULT_STATUSES:
        raise ValueError(f"ExtractionRun.status cannot be result status {value!r}")
    if value not in _VALID_RUN_STATUSES:
        raise ValueError(f"Invalid run status: {value!r}")
    return value


class RunRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        run_id: str,
        backend: str,
        model: str,
        status: RunStatus | str = RunStatus.PENDING,
        prompt_name: str = "",
        input_dir: str | None = None,
        mode: str = "normal",
        config: dict | None = None,
        workers: int | None = None,
        image_format: str | None = None,
        max_width: int | None = None,
        encode_quality: int | None = None,
        grayscale: bool | None = None,
        context_length: int | None = None,
        reasoning_mode: str | None = None,
        eval_batch_size: int | None = None,
        physical_batch_size: int | None = None,
        flash_attention: bool | None = None,
        offload_kv_cache_to_gpu: bool | None = None,
        max_completion_tokens: int | None = None,
        temperature: float | None = None,
        max_retries: int | None = None,
        timeout_connect: int | None = None,
        timeout_read: int | None = None,
        performance_tps_floor: float | None = None,
        performance_reload_elapsed_s: float | None = None,
        performance_reload_streak: int | None = None,
    ) -> ExtractionRunEntity:
        entity = ExtractionRunEntity(
            id=run_id,
            backend=backend,
            model=model,
            status=_status_value(status),
            mode=mode,
            prompt_name=prompt_name,
            input_dir=input_dir,
            config_extra_json=_run_config_dumps(config or {}),
            workers=int(workers or 1),
            image_format=image_format,
            max_width=max_width,
            encode_quality=encode_quality,
            grayscale=bool(grayscale) if grayscale is not None else False,
            context_length=context_length,
            reasoning_mode=reasoning_mode,
            eval_batch_size=eval_batch_size,
            physical_batch_size=physical_batch_size,
            flash_attention=flash_attention,
            offload_kv_cache_to_gpu=offload_kv_cache_to_gpu,
            max_completion_tokens=max_completion_tokens,
            temperature=temperature,
            max_retries=max_retries,
            timeout_connect=timeout_connect,
            timeout_read=timeout_read,
            performance_tps_floor=performance_tps_floor,
            performance_reload_elapsed_s=performance_reload_elapsed_s,
            performance_reload_streak=performance_reload_streak,
        )
        if entity.status == RunStatus.RUNNING.value:
            entity.started_at = datetime.now(timezone.utc)
        self.session.add(entity)
        return entity

    def upsert(
        self,
        *,
        run_id: str,
        backend: str,
        model: str,
        status: RunStatus | str = RunStatus.COMPLETED,
        prompt_name: str = "",
        input_dir: str | None = None,
        mode: str | None = None,
        config: dict | None = None,
    ) -> ExtractionRunEntity:
        existing = self.by_id(run_id)
        status_value = _status_value(status)
        if existing is not None:
            existing.backend = backend
            existing.model = model
            existing.status = status_value
            if mode is not None:
                existing.mode = mode
            if prompt_name:
                existing.prompt_name = prompt_name
            if input_dir is not None:
                existing.input_dir = input_dir
            existing_config = _run_config_loads(existing.config_extra_json)
            existing.config_extra_json = _run_config_dumps(config or existing_config or {})
            self.session.add(existing)
            return existing
        return self.create(
            run_id=run_id,
            backend=backend,
            model=model,
            status=status_value,
            prompt_name=prompt_name,
            input_dir=input_dir,
            mode=mode or "normal",
            config=config,
        )

    def by_id(self, run_id: str) -> ExtractionRunEntity | None:
        return self.session.get(ExtractionRunEntity, run_id)

    def complete(
        self,
        run_id: str,
        *,
        status: RunStatus | str = RunStatus.COMPLETED,
        metrics: dict | None = None,
    ) -> ExtractionRunEntity | None:
        entity = self.by_id(run_id)
        if entity is None:
            return None
        now = datetime.now(timezone.utc)
        entity.status = _status_value(status)
        entity.finished_at = now
        if metrics:
            for key in _FLAT_METRIC_KEYS:
                if key in metrics and metrics[key] is not None:
                    setattr(entity, key, int(metrics[key]))
            if "operational_error_message" in metrics:
                entity.operational_error_message = metrics.get("operational_error_message")
            extra = {
                key: value
                for key, value in metrics.items()
                if key not in _NON_EXTRA_METRIC_KEYS
            }
            if extra:
                current_config = _run_config_loads(entity.config_extra_json)
                entity.config_extra_json = _run_config_dumps({**current_config, **extra})
        self.session.add(entity)
        return entity

    def fail(
        self,
        run_id: str,
        *,
        error: str,
        error_code: str | None = None,
    ) -> ExtractionRunEntity | None:
        entity = self.by_id(run_id)
        if entity is None:
            return None
        now = datetime.now(timezone.utc)
        entity.status = RunStatus.FAILED.value
        entity.finished_at = now
        entity.operational_error_message = error
        entity.operational_error_code = error_code
        self.session.add(entity)
        return entity

    def latest(self) -> ExtractionRunEntity | None:
        return self.session.exec(
            select(ExtractionRunEntity).order_by(
                func.coalesce(ExtractionRunEntity.started_at, ExtractionRunEntity.created_at).desc(),
                ExtractionRunEntity.id.desc(),
            )
        ).first()

    def latest_completed(self) -> ExtractionRunEntity | None:
        return self.session.exec(
            select(ExtractionRunEntity)
            .where(ExtractionRunEntity.status == RunStatus.COMPLETED.value)
            .order_by(ExtractionRunEntity.finished_at.desc(), ExtractionRunEntity.started_at.desc())
        ).first()

    def refresh_review_counts(self, *, run_ids: Iterable[str] | None = None) -> None:
        scoped_ids = None if run_ids is None else {str(run_id) for run_id in run_ids if run_id}
        if scoped_ids is not None and not scoped_ids:
            return

        count_query = (
            select(ReviewCaseEntity.run_id, func.count())
            .where(
                ReviewCaseEntity.run_id.is_not(None),
                ReviewCaseEntity.status == "open",
            )
            .group_by(ReviewCaseEntity.run_id)
        )
        run_query = select(ExtractionRunEntity)
        if scoped_ids is not None:
            count_query = count_query.where(ReviewCaseEntity.run_id.in_(scoped_ids))
            run_query = run_query.where(ExtractionRunEntity.id.in_(scoped_ids))

        counts = {
            run_id: int(count)
            for run_id, count in self.session.exec(count_query).all()
        }
        for run in self.session.exec(run_query).all():
            run.review_case_count = counts.get(run.id, 0)
            self.session.add(run)

    def to_schema(self, entity: ExtractionRunEntity) -> ExtractionRun:
        return ExtractionRun(
            id=entity.id,
            backend=entity.backend,
            model=entity.model,
            prompt_name=entity.prompt_name or "",
            status=entity.status,
            started_at=entity.started_at,
            finished_at=entity.finished_at,
            processed=entity.processed,
            succeeded=entity.succeeded,
            failed=entity.failed,
            review_case_count=entity.review_case_count,
            input_dir=entity.input_dir,
            run_config=_run_config_loads(entity.config_extra_json),
            operational_error_message=entity.operational_error_message,
        )
