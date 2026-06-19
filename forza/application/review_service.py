from __future__ import annotations

from pathlib import Path

from sqlalchemy import func
from sqlmodel import Session, select

from ..db.models import ReviewCaseEntity
from ..db.repositories import (
    ImageFlagRepository,
    LapRepository,
    ReviewCorrectionRepository,
    ReviewRepository,
    RunRepository,
)
from ..schemas import ReviewCase, ReviewReason
from .db_session_provider import DbSessionProvider


class ReviewService:
    """Owns review case reads and derived refresh orchestration."""

    def __init__(self, session_provider: DbSessionProvider, database_file: Path):
        self._session_provider = session_provider
        self.database_file = Path(database_file)

    def refresh_review_cases(self, *, run_id: str | None = None) -> tuple[int, int, int]:
        # Review and flag state is globally derived. The run_id argument is kept
        # for DatabaseService compatibility but must not scope the refresh.
        _ = run_id
        with Session(self._session_provider.engine_for_db()) as session:
            counts = self.refresh_review_cases_in_session(session)
            RunRepository(session).refresh_review_counts()
            session.commit()
            return counts

    def refresh_review_cases_in_session(self, session: Session) -> tuple[int, int, int]:
        # Review and flag state is globally derived. A run-scoped refresh would
        # auto-resolve valid cases owned by other runs.
        ReviewCorrectionRepository(session).apply_all()
        candidates = LapRepository(session).query_review_candidates()
        repo = ReviewRepository(session)
        inserted, kept, removed = repo.upsert_review_cases(candidates)
        session.flush()
        flags = ImageFlagRepository(session)
        open_cases = repo.open_cases()
        desired_flag_keys: set[str] = set()
        for case in open_cases:
            if not case.image_file_id:
                continue
            flag = flags.add_flag(
                image_file_id=case.image_file_id,
                flag=case.reason,
                run_id=case.run_id,
                extraction_result_id=case.extraction_result_id,
                lap_record_id=case.lap_record_id,
                reason=case.reason,
            )
            desired_flag_keys.add(flag.flag_key)
        review_reasons = {reason.value for reason in ReviewReason}
        for flag in flags.list_open():
            if (
                flag.created_by == "system"
                and flag.flag_type in review_reasons
                and flag.flag_key not in desired_flag_keys
            ):
                flags.resolve(flag.id)
        return inserted, kept, removed

    def list_open_review_cases(self) -> list[ReviewCase]:
        if not self.database_file.exists():
            return []
        with Session(self._session_provider.engine_for_db()) as session:
            rows = session.exec(
                select(ReviewCaseEntity).where(ReviewCaseEntity.status == "open")
            ).all()
            return [_review_case_from_entity(row) for row in rows]

    def count_review_cases(
        self,
        *,
        run_id: str | None = None,
        status: str | None = None,
    ) -> int:
        with Session(self._session_provider.engine_for_db()) as session:
            query = select(func.count()).select_from(ReviewCaseEntity)
            if run_id is not None:
                query = query.where(ReviewCaseEntity.run_id == run_id)
            if status is not None:
                query = query.where(ReviewCaseEntity.status == status)
            return session.exec(query).one()


ReviewReadService = ReviewService


def _review_case_from_entity(row: ReviewCaseEntity) -> ReviewCase:
    return ReviewCase(
        reason=row.reason,
        source_file=row.source_file,
        track=row.track,
        race_class=row.race_class,
        weather=row.weather,
        temp_f=row.temp_f,
        driver=row.driver,
        car=row.car,
        best_lap=row.best_lap,
        case_number=row.case_number,
        image_file_id=row.image_file_id,
        run_id=row.run_id,
        extraction_result_id=row.extraction_result_id,
        lap_record_id=row.lap_record_id,
        lap_index=row.lap_index,
        trigger=row.trigger,
        model_value=row.model_value,
        outcome=row.outcome,
        decision_field=row.decision_field,
        corrected_value=row.corrected_value,
        error_type=row.error_type,
        track_suggestions=list(row.track_suggestions_json or []),
    )


__all__ = ["ReviewReadService", "ReviewService"]
