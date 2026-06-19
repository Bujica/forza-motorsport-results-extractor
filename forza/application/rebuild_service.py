from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session

from ..db.repositories import LapRepository, ReviewCorrectionRepository, RunRepository
from ..events import EventSink, EventType, emit_event
from .db_session_provider import DbSessionProvider
from .review_service import ReviewService

if TYPE_CHECKING:
    from .database_service import DatabaseService


class ReviewRefreshResult(list):
    def __init__(self, cases: list, *, inserted: int, kept: int, removed: int):
        super().__init__(cases)
        self.inserted = inserted
        self.kept = kept
        self.removed = removed

    @property
    def counts(self) -> tuple[int, int, int]:
        return self.inserted, self.kept, self.removed


class RebuildService:
    """Application boundary for no-model derived-state rebuilds.

    Rebuild updates relational derived state only. External record imports and PDF
    generation are explicit Best Laps actions.
    """

    def __init__(
        self,
        *,
        database_service: DatabaseService | None = None,
        event_sink: EventSink | None = None,
        session_provider: DbSessionProvider | None = None,
        review_service: ReviewService | None = None,
    ):
        self.database_service = database_service
        self.event_sink = event_sink
        self._session_provider = session_provider
        self._review_service = review_service

    def rebuild_derived_state(self, *, gamertag: str | None = None) -> tuple[int, tuple[int, int, int]]:
        """Atomically rebuild best laps, review cases, and system review flags."""
        if self._session_provider is None or self._review_service is None:
            raise RuntimeError("RebuildService requires session_provider and review_service for derived-state rebuilds")
        with Session(self._session_provider.engine_for_db()) as session:
            ReviewCorrectionRepository(session).apply_all()
            winners = LapRepository(session).mark_best_laps(gamertag=gamertag)
            review_counts = self._review_service.refresh_review_cases_in_session(session)
            RunRepository(session).refresh_review_counts()
            session.commit()
            return len(winners), review_counts

    def rebuild_outputs(
        self,
        cfg,
        refs,
        log,
        *,
        run_id: str | None = None,
    ) -> ReviewRefreshResult:
        database = self._database(cfg)
        owns_database = self.database_service is None

        try:
            database.seed_references(tracks=list(refs.tracks), cars=list(refs.cars))
            log.info("Computing relational best-lap records...")
            _winner_count, review_counts = database.rebuild_derived_state(
                gamertag=cfg.gamertag
            )

            inserted, kept, removed = review_counts
            open_cases = database.list_open_review_cases()
            emit_event(
                self.event_sink,
                EventType.REVIEW_CASES_CREATED,
                run_id=run_id,
                count=inserted + kept,
                inserted=inserted,
                kept=kept,
                removed=removed,
            )
            return ReviewRefreshResult(open_cases, inserted=inserted, kept=kept, removed=removed)
        finally:
            if owns_database:
                database.close()

    # ── Private helpers ──────────────────────────────────────────────────
    def _database(self, cfg) -> DatabaseService:
        if self.database_service is not None:
            return self.database_service
        from .database_service import DatabaseService

        return DatabaseService(cfg.database_file)
