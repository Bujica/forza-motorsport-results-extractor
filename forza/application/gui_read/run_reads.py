from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import select

from ...db.models import ExtractionRunEntity
from ...db.repositories import RunRepository
from ...schemas import ExtractionRun
from .session_provider import GuiReadSessionProvider
from .types import GuiRunOption


class GuiRunReadQueries:
    """Read queries for GUI run selectors and run details."""

    def __init__(self, session_provider: GuiReadSessionProvider):
        self._session_provider = session_provider

    def list_runs(self, *, limit: int = 50) -> list[ExtractionRun]:
        if not self._session_provider.can_read():
            return []
        with self._session_provider.session() as session:
            rows = session.exec(
                select(ExtractionRunEntity)
                .order_by(ExtractionRunEntity.started_at.desc(), ExtractionRunEntity.id.desc())
                .limit(max(limit, 0))
            ).all()
            repo = RunRepository(session)
            return [repo.to_schema(row) for row in rows]

    def list_run_options(self, *, limit: int = 100) -> list[GuiRunOption]:
        if not self._session_provider.can_read():
            return []
        with self._session_provider.session() as session:
            rows = session.exec(
                select(ExtractionRunEntity)
                .order_by(ExtractionRunEntity.started_at.desc(), ExtractionRunEntity.id.desc())
                .limit(max(limit, 0))
            ).all()
            return [_run_option(row) for row in rows]

    def get_run(self, run_id: str) -> ExtractionRun | None:
        if not self._session_provider.can_read():
            return None
        with self._session_provider.session() as session:
            row = session.get(ExtractionRunEntity, run_id)
            return RunRepository(session).to_schema(row) if row is not None else None


def _run_option(row: ExtractionRunEntity | None) -> GuiRunOption:
    if row is None:
        return GuiRunOption(id="", label="")
    started = _local_datetime_label(row.started_at) if row.started_at is not None else row.id
    processed = int(row.processed or 0)
    if processed == 0:
        processed = int(row.succeeded or 0) + int(row.failed or 0)
    label = f"{started} · {processed} processed · {row.mode} · {row.status}"
    return GuiRunOption(id=row.id, label=label)


def _local_datetime_label(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")
