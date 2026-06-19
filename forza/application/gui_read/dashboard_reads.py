from __future__ import annotations

from sqlalchemy import func
from sqlmodel import select

from ...db.models import (
    ExtractionResultEntity,
    ExtractionRunEntity,
    LapRecordEntity,
    ReviewCaseEntity,
    ImageFileEntity,
)
from .session_provider import GuiReadSessionProvider
from .types import DashboardSummary


class GuiDashboardReadQueries:
    """Read queries for dashboard counts."""

    def __init__(self, session_provider: GuiReadSessionProvider):
        self._session_provider = session_provider

    def dashboard_summary(self) -> DashboardSummary:
        if not self._session_provider.can_read():
            return DashboardSummary(0, 0, 0, 0, 0, 0, 0, 0, 0)
        with self._session_provider.session() as session:
            def _count(entity, *where):
                query = select(func.count()).select_from(entity)
                for clause in where:
                    query = query.where(clause)
                return session.exec(query).one()

            return DashboardSummary(
                images=_count(ImageFileEntity),
                available_images=_count(ImageFileEntity, ImageFileEntity.file_status == "available"),
                missing_images=_count(ImageFileEntity, ImageFileEntity.file_status == "missing"),
                best_lap_images=_count(ImageFileEntity, ImageFileEntity.best_lap_status == "contributing"),
                review_open=_count(ReviewCaseEntity, ReviewCaseEntity.status == "open"),
                runs=_count(ExtractionRunEntity),
                extraction_results=_count(ExtractionResultEntity),
                lap_records=_count(LapRecordEntity),
                best_laps=_count(LapRecordEntity, LapRecordEntity.is_best_lap == True),  # noqa: E712
            )
