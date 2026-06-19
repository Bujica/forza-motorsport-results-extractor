from __future__ import annotations

from sqlmodel import Session

from ..db.repositories import ReferenceRepository
from ..domain.normalizer import ReferenceData, _build_car_map
from .db_session_provider import DbSessionProvider


class ReferenceDataService:
    """Owns database-backed reference data reads, seeding, and loading."""

    def __init__(self, session_provider: DbSessionProvider):
        self._session_provider = session_provider

    def seed_references(self, *, tracks: list[str], cars: list[str]) -> tuple[int, int]:
        with Session(self._session_provider.engine_for_db()) as session:
            repo = ReferenceRepository(session)
            added_tracks = repo.seed_tracks(tracks)
            added_cars = repo.seed_cars(cars)
            session.commit()
            return added_tracks, added_cars

    def list_reference_tracks(self) -> list[str]:
        with Session(self._session_provider.engine_for_db()) as session:
            return ReferenceRepository(session).list_tracks()

    def list_reference_cars(self) -> list[str]:
        with Session(self._session_provider.engine_for_db()) as session:
            return ReferenceRepository(session).list_cars()

    def load_reference_data(self) -> ReferenceData:
        """Load production references from SQLite only."""
        cars = self.list_reference_cars()
        return ReferenceData(
            tracks=self.list_reference_tracks(),
            cars=cars,
            car_map=_build_car_map(cars),
        )


__all__ = ["ReferenceDataService"]
