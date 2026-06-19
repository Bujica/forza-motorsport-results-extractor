from __future__ import annotations

from sqlmodel import Session, select

from ...db.models import LapRecordEntity, ReviewCaseEntity
from .session_provider import GuiReadSessionProvider
from .types import GuiReviewCase


class GuiReviewReadQueries:
    """Read queries for GUI review queue screens."""

    def __init__(self, session_provider: GuiReadSessionProvider):
        self._session_provider = session_provider

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
        if not self._session_provider.can_read():
            return []
        with self._session_provider.session() as session:
            query = select(ReviewCaseEntity)
            if status is not None and status != "all":
                query = query.where(ReviewCaseEntity.status == status)
            if reason is not None and reason != "all":
                query = query.where(ReviewCaseEntity.reason == reason)
            if outcome is not None and outcome != "all":
                query = query.where(ReviewCaseEntity.outcome == outcome)
            if run_id is not None and run_id != "all":
                query = query.where(ReviewCaseEntity.run_id == run_id)
            if image_file_id is not None and image_file_id != "all":
                query = query.where(ReviewCaseEntity.image_file_id == image_file_id)
            query = query.order_by(ReviewCaseEntity.created_at.asc()).offset(max(offset, 0))
            if limit is not None:
                query = query.limit(max(limit, 0))
            rows = session.exec(query).all()
            rows = sorted(rows, key=lambda row: (0 if row.outcome == "model_error" else 1, row.created_at))
            return [_review_case(row, _current_review_lap(session, row)) for row in rows]


def _review_case(row: ReviewCaseEntity, current_lap: LapRecordEntity | None = None) -> GuiReviewCase:
    return GuiReviewCase(
        id=row.id,
        case_number=row.case_number,
        business_key=row.business_key,
        image_file_id=row.image_file_id,
        run_id=row.run_id,
        extraction_result_id=row.extraction_result_id,
        lap_record_id=row.lap_record_id,
        source_file=row.source_file,
        reason=row.reason,
        trigger=row.trigger,
        outcome=row.outcome,
        decision_field=row.decision_field,
        model_value=row.model_value,
        corrected_value=row.corrected_value,
        error_type=row.error_type,
        track=row.track,
        race_class=row.race_class,
        weather=row.weather,
        temp_f=row.temp_f,
        driver=row.driver,
        car=row.car,
        best_lap=row.best_lap,
        current_track=current_lap.track if current_lap is not None else None,
        current_race_class=current_lap.race_class if current_lap is not None else None,
        current_weather=current_lap.weather if current_lap is not None else None,
        current_driver=current_lap.driver if current_lap is not None else None,
        current_car=current_lap.car if current_lap is not None else None,
        current_best_lap=current_lap.best_lap if current_lap is not None else None,
        current_dirty=current_lap.dirty if current_lap is not None else None,
        status=row.status,
        resolution_note=row.resolution_note,
        track_suggestions=list(row.track_suggestions_json or []),
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


def _current_review_lap(session: Session, row: ReviewCaseEntity) -> LapRecordEntity | None:
    if row.lap_record_id:
        lap = session.get(LapRecordEntity, row.lap_record_id)
        if lap is not None:
            return lap
    if row.image_file_id and row.lap_index is not None:
        return session.exec(
            select(LapRecordEntity).where(
                LapRecordEntity.image_file_id == row.image_file_id,
                LapRecordEntity.lap_index == row.lap_index,
            )
        ).first()
    if row.image_file_id:
        return session.exec(
            select(LapRecordEntity)
            .where(LapRecordEntity.image_file_id == row.image_file_id)
            .order_by(LapRecordEntity.lap_index)
        ).first()
    return None
