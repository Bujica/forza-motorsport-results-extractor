from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import func
from sqlmodel import Session, select

from ..db.models import (
    ExtractionResultEntity,
    ExtractionRunEntity,
    PromptSnapshotEntity,
    ReviewCaseEntity,
    RunInputEntity,
)
from ..db.repositories import RunRepository
from ..schemas import RunStatus
from .db_session_provider import DbSessionProvider


_log = logging.getLogger("forza")


class RunLifecycleService:
    """Owns run lifecycle persistence helpers."""

    def __init__(self, session_provider: DbSessionProvider):
        self._session_provider = session_provider

    def begin_run(
        self,
        *,
        run_id: str,
        backend: str,
        model: str,
        prompt_name: str,
        input_dir: str,
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
    ) -> None:
        from ..prompts import prompt_content_hash, prompt_snapshot_id, prompt_snapshot_payload

        try:
            prompt_hash = prompt_content_hash(prompt_name)
            snapshot_id = prompt_snapshot_id(prompt_name)
            prompt_payload = prompt_snapshot_payload(prompt_name)
        except ValueError:
            import hashlib

            prompt_hash = hashlib.sha256(prompt_name.encode("utf-8")).hexdigest()
            snapshot_id = f"{prompt_name}:{prompt_hash}"
            prompt_payload = {
                "system_text": "",
                "user_text_template": None,
                "response_schema_json": None,
            }
        with Session(self._session_provider.engine_for_db()) as session:
            existing_prompt = session.get(PromptSnapshotEntity, snapshot_id)
            if existing_prompt is None:
                session.add(PromptSnapshotEntity(
                    id=snapshot_id,
                    prompt_name=prompt_name,
                    content_hash=prompt_hash,
                    system_text=str(prompt_payload["system_text"] or ""),
                    user_text_template=prompt_payload["user_text_template"],
                    response_schema_json=prompt_payload["response_schema_json"],
                ))
            elif (
                existing_prompt.prompt_name != prompt_name
                or existing_prompt.content_hash != prompt_hash
                or existing_prompt.system_text != str(prompt_payload["system_text"] or "")
                or existing_prompt.user_text_template != prompt_payload["user_text_template"]
                or existing_prompt.response_schema_json != prompt_payload["response_schema_json"]
            ):
                raise RuntimeError(
                    "Prompt snapshot is immutable and no longer matches its "
                    f"deterministic identity: {snapshot_id}"
                )
            RunRepository(session).create(
                run_id=run_id,
                backend=backend,
                model=model,
                status=RunStatus.RUNNING,
                prompt_name=prompt_name,
                input_dir=input_dir,
                mode=mode,
                config=config or {},
                workers=workers,
                image_format=image_format,
                max_width=max_width,
                encode_quality=encode_quality,
                grayscale=grayscale,
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
            run = session.get(ExtractionRunEntity, run_id)
            if run is not None:
                run.prompt_snapshot_id = snapshot_id
                run.prompt_name = prompt_name
                run.prompt_hash = prompt_hash
                session.add(run)
            session.commit()

    def complete_run(
        self,
        run_id: str,
        *,
        metrics: dict | None = None,
        status: RunStatus | str = RunStatus.COMPLETED,
    ) -> None:
        with Session(self._session_provider.engine_for_db()) as session:
            status_value = status.value if isinstance(status, RunStatus) else str(status)
            missing = self._missing_process_inputs(session, run_id)
            if missing and status_value == RunStatus.COMPLETED.value:
                raise RuntimeError(
                    f"Cannot complete run {run_id}: {len(missing)} process input(s) have no result"
                )
            nonfinal = int(
                session.exec(
                    select(func.count())
                    .select_from(ExtractionResultEntity)
                    .where(
                        ExtractionResultEntity.run_id == run_id,
                        ExtractionResultEntity.status.in_(["pending", "running"]),
                    )
                ).one()
            )
            if nonfinal and status_value == RunStatus.COMPLETED.value:
                raise RuntimeError(
                    f"Cannot complete run {run_id}: {nonfinal} result(s) are not final"
                )
            resolved_metrics = self.run_metrics(session, run_id, extras=metrics)
            RunRepository(session).complete(run_id, status=status_value, metrics=resolved_metrics)
            session.commit()

    def fail_run(self, run_id: str, *, error: str, error_code: str | None = None) -> None:
        with Session(self._session_provider.engine_for_db()) as session:
            RunRepository(session).fail(run_id, error=error, error_code=error_code or error)
            session.commit()

    def fail_preflight_run(self, run_id: str, *, error: str) -> None:
        """Fail before chat without leaving process decisions that require results."""
        with Session(self._session_provider.engine_for_db()) as session:
            rows = session.exec(
                select(RunInputEntity).where(
                    RunInputEntity.run_id == run_id,
                    RunInputEntity.decision == "process",
                )
            ).all()
            for row in rows:
                row.decision = "skip"
                row.process_reason = None
                row.skip_reason = "preflight_failed"
                session.add(row)
            run = session.get(ExtractionRunEntity, run_id)
            if run is not None:
                run.to_process = 0
                run.skipped = int(run.skipped or 0) + len(rows)
                session.add(run)
            RunRepository(session).fail(
                run_id,
                error=error,
                error_code="lmstudio_preflight_failed",
            )
            session.commit()

    def latest_completed_run_id(self) -> str | None:
        with Session(self._session_provider.engine_for_db()) as session:
            latest = RunRepository(session).latest_completed()
            return latest.id if latest is not None else None

    def reconcile_interrupted_run(
        self,
        run_id: str,
        *,
        status: RunStatus | str,
        error: str,
    ) -> None:
        """Finalize every process input after cooperative cancel or abrupt failure."""
        status_value = status.value if isinstance(status, RunStatus) else str(status)
        with Session(self._session_provider.engine_for_db()) as session:
            run = session.get(ExtractionRunEntity, run_id)
            if run is None:
                return
            for run_input in session.exec(
                select(RunInputEntity).where(
                    RunInputEntity.run_id == run_id,
                    RunInputEntity.decision == "process",
                )
            ).all():
                result = session.exec(
                    select(ExtractionResultEntity).where(
                        ExtractionResultEntity.run_input_id == run_input.id
                    )
                ).first()
                if result is None:
                    result = ExtractionResultEntity(
                        id=uuid4().hex,
                        run_id=run_id,
                        run_input_id=run_input.id,
                        image_file_id=run_input.image_file_id,
                        status="cancelled",
                        error_type="cancelled",
                        error_message=error,
                        model=run.model,
                        prompt_snapshot_id=run.prompt_snapshot_id,
                    )
                elif result.status in {"pending", "running"}:
                    result.status = "cancelled"
                    result.error_type = "cancelled"
                    result.error_message = error
                session.add(result)
            metrics = self.run_metrics(
                session,
                run_id,
                extras={"operational_error_message": error},
            )
            RunRepository(session).complete(run_id, status=status_value, metrics=metrics)
            run.operational_error_code = (
                "cancelled_by_user"
                if status_value == RunStatus.CANCELLED.value
                else error.split(":", 1)[0]
            )
            run.operational_error_message = error
            session.add(run)
            session.commit()

    def reconcile_abandoned_runs(self) -> int:
        """Mark runs left running by a prior process crash as failed.

        Returns the number of runs successfully reconciled. One corrupt run must
        not prevent recovery of other abandoned runs found in the same pass.
        """
        with Session(self._session_provider.engine_for_db()) as session:
            run_ids = list(
                session.exec(
                    select(ExtractionRunEntity.id).where(
                        ExtractionRunEntity.status == RunStatus.RUNNING.value
                    )
                ).all()
            )
        recovered = 0
        for run_id in run_ids:
            try:
                self.reconcile_interrupted_run(
                    run_id,
                    status=RunStatus.FAILED,
                    error="abandoned_run_recovered",
                )
            except Exception:
                _log.error("[run] Could not reconcile abandoned run %s", run_id, exc_info=True)
                continue
            recovered += 1
        return recovered

    def run_metrics(
        self,
        session: Session,
        run_id: str,
        *,
        extras: dict | None = None,
    ) -> dict:
        statuses = list(
            session.exec(
                select(ExtractionResultEntity.status).where(
                    ExtractionResultEntity.run_id == run_id
                )
            ).all()
        )
        decisions = list(
            session.exec(
                select(RunInputEntity.decision).where(RunInputEntity.run_id == run_id)
            ).all()
        )
        metrics = dict(extras or {})
        metrics.update({
            "total_inputs": len(decisions),
            "to_process": sum(1 for value in decisions if value == "process"),
            "skipped": sum(1 for value in decisions if value not in {"process", "duplicate"}),
            "duplicate_count": sum(1 for value in decisions if value == "duplicate"),
            "processed": len(statuses),
            "succeeded": sum(1 for value in statuses if value == "ok"),
            "failed": sum(1 for value in statuses if value == "error"),
            "review_case_count": int(
                session.exec(
                    select(func.count())
                    .select_from(ReviewCaseEntity)
                    .where(
                        ReviewCaseEntity.run_id == run_id,
                        ReviewCaseEntity.status == "open",
                    )
                ).one()
            ),
        })
        return metrics

    def _missing_process_inputs(self, session: Session, run_id: str) -> list[int]:
        return [
            row_id
            for row_id in session.exec(
                select(RunInputEntity.id)
                .outerjoin(
                    ExtractionResultEntity,
                    ExtractionResultEntity.run_input_id == RunInputEntity.id,
                )
                .where(
                    RunInputEntity.run_id == run_id,
                    RunInputEntity.decision == "process",
                    ExtractionResultEntity.id.is_(None),
                )
            ).all()
            if row_id is not None
        ]


__all__ = ["RunLifecycleService"]
