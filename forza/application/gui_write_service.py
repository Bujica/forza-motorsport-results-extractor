from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Iterator

from sqlalchemy import func, or_
from sqlmodel import Session, select

from ..db import create_sqlite_engine
from ..db.migrate import is_up_to_date
from ..db.models import (
    ExtractionAttemptEntity,
    ExtractionResultEntity,
    ExtractionRunEntity,
    ImageFlagEntity,
    ImageFileEntity,
    LapRecordEntity,
    ModelArtifactEntity,
    ReviewCaseEntity,
    ReviewCorrectionEntity,
    RunInputEntity,
)
from ..db.repositories import ImageFlagRepository, LapRepository, ReviewCorrectionRepository, RunRepository, ImageFileRepository
from ..events import EventSink, EventType, emit_event
from ..domain.lap import normalize_weather, strip_dirty_symbol
from ..schemas import (
    ReviewCaseStatus,
    ImageFile,
    ImageFileStatus,
)


_IMAGE_FILE_WRITE_STATUSES = {
    ImageFileStatus.AVAILABLE.value,
    ImageFileStatus.MISSING.value,
}
_REVIEW_CASE_WRITE_STATUSES = {
    ReviewCaseStatus.OPEN.value,
    ReviewCaseStatus.RESOLVED.value,
    ReviewCaseStatus.IGNORED.value,
}


@dataclass(frozen=True)
class GuiWriteResult:
    """Small write-result envelope for GUI command handlers."""

    ok: bool
    entity_type: str
    entity_id: str | None = None
    message: str = ""


class ReviewDecisionTargetNotFound(RuntimeError):
    """Raised when a review decision cannot be tied to one lap record."""


@dataclass(frozen=True)
class _BestLapGroup:
    track: str
    race_class: str
    weather: str


class GuiWriteService:
    """Write-side facade for GUI actions.

    GUI screens should avoid mutating SQLModel entities directly. This service
    centralizes common state transitions, commits them atomically, and emits
    events so a UI can refresh only the affected areas.

    A single SQLAlchemy engine is created lazily on first use and reused for
    all subsequent operations. Call ``close()`` (or use as a context manager)
    when the GUI shuts down.
    """

    def __init__(
        self,
        database_file: Path,
        *,
        event_sink: EventSink | None = None,
        gamertag: str | None = None,
    ):
        self.database_file = Path(database_file)
        self.event_sink = event_sink
        self.gamertag = str(gamertag or "").strip() or None
        self._engine = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def __enter__(self) -> "GuiWriteService":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    # ── Image state ────────────────────────────────────────────────────────────

    def set_file_status(self, image_file_id: str, file_status: str) -> ImageFile | None:
        if file_status not in _IMAGE_FILE_WRITE_STATUSES:
            raise ValueError(f"file_status must be one of {sorted(_IMAGE_FILE_WRITE_STATUSES)}")
        with self._session() as session:
            entity = session.get(ImageFileEntity, image_file_id)
            if entity is None:
                return None
            entity.file_status = file_status
            entity.missing_at = datetime.now(timezone.utc) if file_status == "missing" else None
            entity.updated_at = datetime.now(timezone.utc)
            session.add(entity)
            session.commit()
            schema = ImageFileRepository(session).to_schema(entity)
        self._emit(EventType.IMAGE_STATUS_CHANGED, image_file_id=image_file_id, file_status=file_status)
        return schema

    def delete_image_file(self, image_file_id: str) -> bool:
        with self._session() as session:
            entity = session.get(ImageFileEntity, image_file_id)
            if entity is None:
                return False

            result_ids = list(
                session.exec(
                    select(ExtractionResultEntity.id).where(
                        ExtractionResultEntity.image_file_id == image_file_id
                    )
                ).all()
            )
            attempt_ids = list(
                session.exec(
                    select(ExtractionAttemptEntity.id).where(
                        ExtractionAttemptEntity.image_file_id == image_file_id
                    )
                ).all()
            )
            run_ids = _image_run_ids(session, image_file_id)

            _reconcile_duplicate_group_after_delete(session, entity)

            for result in session.exec(
                select(ExtractionResultEntity).where(ExtractionResultEntity.image_file_id == image_file_id)
            ).all():
                result.accepted_attempt_id = None
                session.add(result)
            session.flush()

            _delete_rows(
                session,
                ModelArtifactEntity,
                _artifact_delete_condition(image_file_id, result_ids, attempt_ids),
            )
            _delete_rows(session, ImageFlagEntity, ImageFlagEntity.image_file_id == image_file_id)
            _delete_rows(session, ReviewCorrectionEntity, ReviewCorrectionEntity.image_file_id == image_file_id)
            _delete_rows(session, ReviewCaseEntity, ReviewCaseEntity.image_file_id == image_file_id)
            _delete_rows(session, LapRecordEntity, LapRecordEntity.image_file_id == image_file_id)
            _delete_rows(session, ExtractionAttemptEntity, ExtractionAttemptEntity.image_file_id == image_file_id)
            _delete_rows(session, ExtractionResultEntity, ExtractionResultEntity.image_file_id == image_file_id)
            _delete_rows(session, RunInputEntity, RunInputEntity.image_file_id == image_file_id)

            session.delete(entity)
            _recompute_best_laps(session, self.gamertag)
            _refresh_run_metrics(session, run_ids)
            session.commit()

        self._emit(EventType.IMAGE_STATUS_CHANGED, image_file_id=image_file_id, deleted=True)
        return True

    # ── Review cases ───────────────────────────────────────────────────────────

    def resolve_review_case(self, case_id: str) -> ReviewCaseEntity | None:
        return self._set_review_case_status(case_id, "resolved")

    def ignore_review_case(self, case_id: str) -> ReviewCaseEntity | None:
        return self._set_review_case_status(case_id, "ignored")

    def reopen_review_case(self, case_id: str) -> ReviewCaseEntity | None:
        return self._set_review_case_status(case_id, "open")

    def set_lap_dirty(self, lap_record_id: str, dirty: bool) -> LapRecordEntity | None:
        with self._session() as session:
            entity = session.get(LapRecordEntity, lap_record_id)
            if entity is None:
                return None
            entity.dirty = dirty
            if not dirty:
                entity.best_lap = strip_dirty_symbol(entity.best_lap)
            session.add(entity)
            _recompute_best_laps(session, self.gamertag)
            session.commit()
            session.refresh(entity)
        self._emit(
            EventType.LAP_RECORD_CORRECTED,
            image_file_id=entity.image_file_id,
            lap_record_id=entity.id,
            field="dirty",
            value=dirty,
        )
        return entity

    def set_lap_track(self, lap_record_id: str, track: str) -> LapRecordEntity | None:
        with self._session() as session:
            entity = session.get(LapRecordEntity, lap_record_id)
            if entity is None:
                return None
            laps = _source_laps(session, entity.image_file_id)
            affected_groups = {_best_lap_group(lap) for lap in laps}
            for lap in laps:
                lap.track = track
                session.add(lap)
            affected_groups.update(_best_lap_group(lap) for lap in laps)
            _invalidate_best_lap_groups(session, affected_groups)
            session.commit()
            session.refresh(entity)
        self._emit(
            EventType.LAP_RECORD_CORRECTED,
            image_file_id=entity.image_file_id,
            lap_record_id=entity.id,
            field="track",
            value=track,
        )
        return entity

    def set_lap_weather(self, lap_record_id: str, weather: str) -> LapRecordEntity | None:
        canonical_weather = normalize_weather(weather)
        with self._session() as session:
            entity = session.get(LapRecordEntity, lap_record_id)
            if entity is None:
                return None
            laps = _source_laps(session, entity.image_file_id)
            affected_groups = {_best_lap_group(lap) for lap in laps}
            for lap in laps:
                lap.weather = canonical_weather
                session.add(lap)
            affected_groups.update(_best_lap_group(lap) for lap in laps)
            _invalidate_best_lap_groups(session, affected_groups)
            session.commit()
            session.refresh(entity)
        self._emit(
            EventType.LAP_RECORD_CORRECTED,
            image_file_id=entity.image_file_id,
            lap_record_id=entity.id,
            field="weather",
            value=canonical_weather,
        )
        return entity

    def resolve_review_case_with_decision(
        self,
        case_id: str,
        *,
        lap_record_id: str | None,
        decision: dict[str, Any],
    ) -> ReviewCaseEntity | None:
        field = str(decision.get("field") or "").strip()
        value = decision.get("value")
        if field not in {"dirty", "track", "weather", "race_class", "car", "driver"}:
            raise ValueError("decision field must be one of ['dirty', 'track', 'weather', 'race_class', 'car', 'driver']")

        with self._session() as session:
            case = session.get(ReviewCaseEntity, case_id)
            if case is None:
                return None
            target_lap_id = lap_record_id or case.lap_record_id
            event_lap_id = target_lap_id

            model_value: object | None = None
            if field in {"track", "weather", "race_class"}:
                laps = _case_source_laps(session, case, target_lap_id)
                if not laps:
                    raise ReviewDecisionTargetNotFound(
                        f"Review case {case_id} is not linked to any lap records."
                    )
                event_lap_id = target_lap_id or laps[0].id
                model_value = _field_value(laps[0], field)
                affected_groups = {_best_lap_group(lap) for lap in laps}
                if field == "weather":
                    value = normalize_weather(str(value))
                for lap in laps:
                    if field == "track":
                        lap.track = str(value)
                        lap.track_normalized = str(value).casefold()
                    elif field == "race_class":
                        lap.race_class = str(value)
                    else:
                        lap.weather = str(value)
                    session.add(lap)
                _recompute_best_laps(session, self.gamertag)
            else:
                lap = session.get(LapRecordEntity, target_lap_id) if target_lap_id else _find_case_lap(session, case)
                if lap is None:
                    raise ReviewDecisionTargetNotFound(
                        f"Review case {case_id} is not linked to a unique lap record."
                    )
                event_lap_id = lap.id
                affected_groups = {_best_lap_group(lap)}
                model_value = _field_value(lap, field)
                if field == "dirty":
                    value = _parse_decision_bool(value)
                    lap.dirty = value
                    if not value:
                        lap.best_lap = strip_dirty_symbol(lap.best_lap)
                elif field == "car":
                    lap.car = str(value)
                    lap.car_normalized = str(value).casefold()
                elif field == "driver":
                    lap.driver = str(value)
                    lap.driver_normalized = str(value).casefold()
                session.add(lap)
                _recompute_best_laps(session, self.gamertag)
            corrected_value = _decision_value(value)
            case.lap_record_id = event_lap_id
            case.status = "resolved"
            case.resolved_at = datetime.now(timezone.utc)
            case.resolution_note = _decision_note(field, value)
            case.decision_field = field
            case.model_value = _stringify_decision_value(model_value if case.model_value is None else case.model_value)
            case.corrected_value = corrected_value
            case.outcome = _decision_outcome(case.model_value, corrected_value)
            case.error_type = _error_type(case.reason, field, case.outcome, case.model_value, corrected_value)
            case.updated_at = case.resolved_at
            session.add(case)
            ReviewCorrectionRepository(session).upsert_from_case(case)
            _sync_review_flags(session, case, status="resolved")
            RunRepository(session).refresh_review_counts(run_ids=[case.run_id] if case.run_id else [])
            session.commit()
            session.refresh(case)

        self._emit(
            EventType.LAP_RECORD_CORRECTED,
            image_file_id=case.image_file_id,
            review_case_id=case.id,
            lap_record_id=event_lap_id,
            field=field,
            value=value,
        )
        self._emit(
            EventType.REVIEW_CASE_CHANGED,
            image_file_id=case.image_file_id,
            review_case_id=case.id,
            status="resolved",
        )
        return case

    # ── Private helpers ──────────────────────────────────────────────────────


    def _set_review_case_status(self, case_id: str, status: str) -> ReviewCaseEntity | None:
        if status not in _REVIEW_CASE_WRITE_STATUSES:
            raise ValueError(f"review case status must be one of {sorted(_REVIEW_CASE_WRITE_STATUSES)}")
        with self._session() as session:
            entity = session.get(ReviewCaseEntity, case_id)
            if entity is None:
                return None
            entity.status = status
            entity.resolved_at = None if status == "open" else datetime.now(timezone.utc)
            if status == "open":
                entity.resolution_note = None
                entity.outcome = "pending"
                entity.decision_field = None
                entity.corrected_value = None
                entity.error_type = None
            elif status == "ignored":
                entity.outcome = "ignored"
            elif status == "resolved" and entity.outcome == "pending":
                entity.outcome = "confirmed"
            session.add(entity)
            _sync_review_flags(session, entity, status=status)
            RunRepository(session).refresh_review_counts(run_ids=[entity.run_id] if entity.run_id else [])
            session.commit()
            session.refresh(entity)
        self._emit(
            EventType.REVIEW_CASE_CHANGED,
            image_file_id=entity.image_file_id,
            review_case_id=entity.id,
            status=status,
        )
        return entity

    def _emit(self, event_type: EventType, **data: Any) -> None:
        emit_event(self.event_sink, event_type, **data)

    def _get_engine(self):
        if self._engine is None:
            self._require_ready()
            self._engine = create_sqlite_engine(self.database_file)
        return self._engine

    def _require_ready(self) -> None:
        if not self.database_file.exists():
            raise RuntimeError(f"Database does not exist: {self.database_file}")
        if not is_up_to_date(self.database_file):
            raise RuntimeError(
                f"Database is missing or not at the Alembic head: {self.database_file}"
            )

    @contextmanager
    def _session(self) -> Iterator[Session]:
        with Session(self._get_engine()) as session:
            yield session


def _best_lap_group(row: LapRecordEntity) -> _BestLapGroup:
    return _BestLapGroup(
        track=str(row.track or ""),
        race_class=str(row.race_class or ""),
        weather=str(row.weather or "unknown"),
    )


def _delete_rows(session: Session, model: type, condition) -> None:
    for row in session.exec(select(model).where(condition)).all():
        session.delete(row)


def _artifact_delete_condition(
    image_file_id: str,
    result_ids: list[str],
    attempt_ids: list[str],
):
    conditions = [ModelArtifactEntity.image_file_id == image_file_id]
    if result_ids:
        conditions.append(ModelArtifactEntity.extraction_result_id.in_(result_ids))
    if attempt_ids:
        conditions.append(ModelArtifactEntity.attempt_id.in_(attempt_ids))
    return or_(*conditions)


def _reconcile_duplicate_group_after_delete(
    session: Session,
    deleted_image: ImageFileEntity,
) -> None:
    # Keep duplicate relationships and duplicate flags current after asset deletion.
    remaining = list(
        session.exec(
            select(ImageFileEntity)
            .where(
                ImageFileEntity.file_hash == deleted_image.file_hash,
                ImageFileEntity.id != deleted_image.id,
            )
            .order_by(
                ImageFileEntity.created_at.asc(),
                ImageFileEntity.current_name.asc(),
                ImageFileEntity.id.asc(),
            )
        )
    )
    now = datetime.now(timezone.utc)

    stale_children = list(
        session.exec(
            select(ImageFileEntity).where(
                ImageFileEntity.duplicate_of_image_file_id == deleted_image.id,
                ImageFileEntity.file_hash != deleted_image.file_hash,
            )
        )
    )
    for child in stale_children:
        child.duplicate_of_image_file_id = None
        child.updated_at = now
        session.add(child)
        _resolve_active_duplicate_flags(session, child.id)

    if not remaining:
        return

    if len(remaining) == 1:
        only = remaining[0]
        only.duplicate_of_image_file_id = None
        only.updated_at = now
        session.add(only)
        _resolve_active_duplicate_flags(session, only.id)
        return

    canonical = next(
        (image for image in remaining if image.duplicate_of_image_file_id is None),
        remaining[0],
    )
    canonical.duplicate_of_image_file_id = None
    canonical.updated_at = now
    session.add(canonical)
    _resolve_active_duplicate_flags(session, canonical.id)

    for image in remaining:
        if image.id == canonical.id:
            continue
        image.duplicate_of_image_file_id = canonical.id
        image.updated_at = now
        session.add(image)
        _ensure_active_duplicate_flag(session, image.id)


def _ensure_active_duplicate_flag(session: Session, image_file_id: str) -> None:
    flag = ImageFlagRepository(session).add_flag(
        image_file_id=image_file_id,
        flag="duplicate",
        reason="duplicate_file_hash",
    )
    flag.status = "active"
    flag.resolved_at = None
    session.add(flag)


def _resolve_active_duplicate_flags(session: Session, image_file_id: str) -> None:
    now = datetime.now(timezone.utc)
    for flag in session.exec(
        select(ImageFlagEntity).where(
            ImageFlagEntity.image_file_id == image_file_id,
            ImageFlagEntity.flag_type == "duplicate",
            ImageFlagEntity.status == "active",
        )
    ).all():
        flag.status = "resolved"
        flag.resolved_at = now
        session.add(flag)


def _image_run_ids(session: Session, image_file_id: str) -> set[str]:
    run_ids: set[str] = set()
    for model in (
        RunInputEntity,
        ExtractionResultEntity,
        ExtractionAttemptEntity,
        ImageFlagEntity,
        ReviewCaseEntity,
    ):
        run_ids.update(
            str(run_id)
            for run_id in session.exec(select(model.run_id).where(model.image_file_id == image_file_id)).all()
            if run_id
        )
    return run_ids


def _refresh_run_metrics(session: Session, run_ids: set[str]) -> None:
    for run_id in run_ids:
        run = session.get(ExtractionRunEntity, run_id)
        if run is None:
            continue
        decisions = list(
            session.exec(select(RunInputEntity.decision).where(RunInputEntity.run_id == run_id)).all()
        )
        statuses = list(
            session.exec(select(ExtractionResultEntity.status).where(ExtractionResultEntity.run_id == run_id)).all()
        )
        run.total_inputs = len(decisions)
        run.to_process = sum(1 for value in decisions if value == "process")
        run.skipped = sum(1 for value in decisions if value not in {"process", "duplicate"})
        run.duplicate_count = sum(1 for value in decisions if value == "duplicate")
        run.processed = len(statuses)
        run.succeeded = sum(1 for value in statuses if value == "ok")
        run.failed = sum(1 for value in statuses if value == "error")
        run.review_case_count = int(
            session.exec(
                select(func.count())
                .select_from(ReviewCaseEntity)
                .where(
                    ReviewCaseEntity.run_id == run_id,
                    ReviewCaseEntity.status == "open",
                )
            ).one()
        )
        session.add(run)


def _find_case_lap(session: Session, case: ReviewCaseEntity) -> LapRecordEntity | None:
    query = select(LapRecordEntity)
    if case.image_file_id:
        query = query.where(LapRecordEntity.image_file_id == case.image_file_id)
    else:
        query = query.where(LapRecordEntity.source_file == case.source_file)
    if case.extraction_result_id:
        query = query.where(LapRecordEntity.extraction_result_id == case.extraction_result_id)
    if case.run_id:
        query = query.where(LapRecordEntity.run_id == case.run_id)
    if case.driver:
        query = query.where(LapRecordEntity.driver == case.driver)
    if case.car:
        query = query.where(LapRecordEntity.car == case.car)
    if case.best_lap:
        query = query.where(LapRecordEntity.best_lap == case.best_lap)

    rows = session.exec(query).all()
    if len(rows) == 1:
        return rows[0]
    return None


def _sync_review_flags(session: Session, case: ReviewCaseEntity, *, status: str) -> None:
    if not case.image_file_id:
        return
    flag_status = {
        "open": "active",
        "resolved": "resolved",
        "ignored": "ignored",
    }.get(status)
    if flag_status is None:
        return
    query = select(ImageFlagEntity).where(
        ImageFlagEntity.image_file_id == case.image_file_id,
        ImageFlagEntity.flag_type == case.reason,
        ImageFlagEntity.created_by == "system",
    )
    if case.lap_record_id:
        query = query.where(
            or_(
                ImageFlagEntity.lap_record_id == case.lap_record_id,
                ImageFlagEntity.lap_index == case.lap_index,
            )
        )
    else:
        query = query.where(ImageFlagEntity.lap_index == case.lap_index)
    for flag in session.exec(query).all():
        flag.status = flag_status
        flag.resolved_at = None if flag_status == "active" else datetime.now(timezone.utc)
        session.add(flag)


def _field_value(lap: LapRecordEntity, field: str) -> object | None:
    if field == "dirty":
        return lap.dirty
    if field == "track":
        return lap.track
    if field == "weather":
        return lap.weather
    if field == "race_class":
        return lap.race_class
    if field == "car":
        return lap.car
    if field == "driver":
        return lap.driver
    return None


def _decision_value(value: object) -> str:
    return _stringify_decision_value(value)


def _parse_decision_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    text = str(value).strip().casefold()
    if text in {"true", "yes", "y", "1", "dirty"}:
        return True
    if text in {"false", "no", "n", "0", "clean"}:
        return False
    raise ValueError(f"dirty decision must be boolean-like, got {value!r}")


def _stringify_decision_value(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _normalised_decision_value(value: str | None) -> str:
    return str(value or "").strip().casefold()


def _decision_outcome(model_value: str | None, corrected_value: str | None) -> str:
    if _normalised_decision_value(model_value) == _normalised_decision_value(corrected_value):
        return "confirmed"
    return "model_error"


def _error_type(
    reason: str,
    field: str,
    outcome: str,
    model_value: str | None,
    corrected_value: str | None,
) -> str | None:
    if outcome != "model_error":
        return None
    if reason == "dirty_lap":
        if _normalised_decision_value(model_value) == "true" and _normalised_decision_value(corrected_value) == "false":
            return "dirty_lap_false_positive"
        if _normalised_decision_value(model_value) == "false" and _normalised_decision_value(corrected_value) == "true":
            return "dirty_lap_false_negative"
    return f"{field}_wrong"


def _decision_note(field: str, value: object) -> str:
    rendered = _decision_value(value)
    return f"decision:{field}={rendered}"


def _source_laps(session: Session, image_file_id: str) -> list[LapRecordEntity]:
    return list(
        session.exec(
            select(LapRecordEntity)
            .where(LapRecordEntity.image_file_id == image_file_id)
            .order_by(LapRecordEntity.lap_index)
        )
    )


def _case_source_laps(
    session: Session,
    case: ReviewCaseEntity,
    lap_record_id: str | None,
) -> list[LapRecordEntity]:
    if case.image_file_id:
        return _source_laps(session, case.image_file_id)
    if lap_record_id:
        lap = session.get(LapRecordEntity, lap_record_id)
        if lap is not None:
            return _source_laps(session, lap.image_file_id)
    lap = _find_case_lap(session, case)
    return _source_laps(session, lap.image_file_id) if lap is not None else []


def _invalidate_best_lap_groups(session: Session, groups: set[_BestLapGroup]) -> None:
    if not groups:
        return
    affected_image_ids: set[str] = set()
    for group in groups:
        rows = session.exec(
            select(LapRecordEntity).where(
                LapRecordEntity.track == group.track,
                LapRecordEntity.race_class == group.race_class,
                LapRecordEntity.weather == group.weather,
            )
        ).all()
        for lap in rows:
            affected_image_ids.add(lap.image_file_id)
            if lap.is_best_lap:
                lap.is_best_lap = False
                session.add(lap)

    if not affected_image_ids:
        return
    for image in session.exec(select(ImageFileEntity).where(ImageFileEntity.id.in_(affected_image_ids))).all():
        image.best_lap_status = "pending"
        image.updated_at = datetime.now(timezone.utc)
        session.add(image)


def _recompute_best_laps(session: Session, gamertag: str | None) -> None:
    LapRepository(session).mark_best_laps(gamertag=gamertag)
