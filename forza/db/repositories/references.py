from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Session, select

from ..models import ReferenceCarEntity, ReferenceTrackEntity


class ReferenceRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_tracks(self) -> list[str]:
        return [
            row.name
            for row in self.session.exec(
                select(ReferenceTrackEntity).order_by(ReferenceTrackEntity.name.collate("NOCASE"))
            ).all()
        ]

    def list_cars(self) -> list[str]:
        return [
            row.name
            for row in self.session.exec(
                select(ReferenceCarEntity).order_by(ReferenceCarEntity.name.collate("NOCASE"))
            ).all()
        ]

    def upsert_track(self, name: str) -> ReferenceTrackEntity | None:
        return self._upsert(ReferenceTrackEntity, name)

    def upsert_car(self, name: str) -> ReferenceCarEntity | None:
        return self._upsert(ReferenceCarEntity, name)

    def seed_tracks(self, names: list[str]) -> int:
        return sum(1 for name in names if self.upsert_track(name) is not None)

    def seed_cars(self, names: list[str]) -> int:
        return sum(1 for name in names if self.upsert_car(name) is not None)

    def _upsert(self, entity_type, name: str):
        clean = str(name or "").strip()
        if not clean:
            return None
        existing = self.session.exec(
            select(entity_type).where(entity_type.name == clean)
        ).first()
        if existing is not None:
            existing.updated_at = datetime.now(timezone.utc)
            self.session.add(existing)
            return existing
        entity = entity_type(id=uuid4().hex, name=clean)
        self.session.add(entity)
        return entity
