from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import func
from sqlmodel import Session, select

from ..db.models import LapRecordEntity
from ..db.repositories import LapRepository
from .db_session_provider import DbSessionProvider

_log = logging.getLogger("forza")


class BestLapRecomputeService:
    """Owns best-lap recomputation and count reads against the relational store."""

    def __init__(self, session_provider: DbSessionProvider, database_file: Path):
        self._session_provider = session_provider
        self.database_file = Path(database_file)

    def recompute_best_laps(self, *, run_id: str | None = None, gamertag: str | None = None) -> int:
        if not self.database_file.exists():
            return 0
        with Session(self._session_provider.engine_for_db()) as session:
            winners = LapRepository(session).mark_best_laps(run_id=run_id, gamertag=gamertag)
            session.commit()
            return len(winners)

    def count_lap_records(self) -> int:
        with Session(self._session_provider.engine_for_db()) as session:
            return self._count_safe(session, LapRecordEntity)

    def count_best_laps(self) -> int:
        with Session(self._session_provider.engine_for_db()) as session:
            return session.exec(
                select(func.count()).select_from(LapRecordEntity).where(LapRecordEntity.is_best_lap == True)  # noqa: E712
            ).one()

    def _count_safe(self, session: Session, entity_type: type) -> int:
        try:
            return session.exec(select(func.count()).select_from(entity_type)).one()
        except Exception:
            _log.warning("[db] Could not count %s", getattr(entity_type, "__name__", entity_type), exc_info=True)
            return 0
