from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Session, select

from ..models import ExternalLapRecordEntity, ExternalRecordImportEntity
from ...schemas import ExternalLapRecord


_REJECTED_ROW_ISSUE_KINDS = frozenset({"missing_required_fields", "unmapped_track", "invalid_lap"})


def _issue_kind(issue: dict) -> str:
    return str(issue.get("kind", "")) if isinstance(issue, dict) else str(getattr(issue, "kind", ""))


def _rejected_issue_count(issues: list[dict]) -> int:
    return sum(1 for issue in issues if _issue_kind(issue) in _REJECTED_ROW_ISSUE_KINDS)


class ExternalRecordRepository:
    def __init__(self, session: Session):
        self.session = session

    def active_records(self) -> list[ExternalLapRecord]:
        rows = self.session.exec(
            select(ExternalLapRecordEntity)
            .where(ExternalLapRecordEntity.active == True)  # noqa: E712
            .order_by(
                ExternalLapRecordEntity.track,
                ExternalLapRecordEntity.race_class,
                ExternalLapRecordEntity.best_lap_ms,
            )
        ).all()
        return [self.to_schema(row) for row in rows]

    def replace_active_snapshot(
        self,
        records: list[ExternalLapRecord],
        *,
        source_path: str,
        source_hash: str | None = None,
        total_rows: int | None = None,
        issues: list[dict] | None = None,
        rejected_rows: int | None = None,
        import_id: str | None = None,
    ) -> ExternalRecordImportEntity:
        now = datetime.now(timezone.utc)
        issues = issues or []
        active_imports = self.session.exec(
            select(ExternalRecordImportEntity).where(ExternalRecordImportEntity.active == True)  # noqa: E712
        ).all()
        for row in active_imports:
            row.active = False
            self.session.add(row)

        import_row = ExternalRecordImportEntity(
            id=import_id or uuid4().hex,
            source_path=source_path,
            source_hash=source_hash,
            status="active",
            active=True,
            total_rows=total_rows if total_rows is not None else len(records),
            accepted_rows=len(records),
            rejected_rows=_rejected_issue_count(issues) if rejected_rows is None else rejected_rows,
            issue_count=len(issues),
            issues_json=issues,
            imported_at=now,
            activated_at=now,
        )
        self.session.add(import_row)
        self.session.flush()

        active_rows = self.session.exec(
            select(ExternalLapRecordEntity).where(ExternalLapRecordEntity.active == True)  # noqa: E712
        ).all()
        for row in active_rows:
            row.active = False
            self.session.add(row)

        for record in records:
            self.session.add(
                ExternalLapRecordEntity(
                    id=uuid4().hex,
                    import_id=import_row.id,
                    track=record.track,
                    race_class=record.race_class,
                    driver=record.driver,
                    car=record.car,
                    best_lap=record.best_lap,
                    weather="dry",
                    best_lap_ms=int(record.best_lap_ms),
                    active=True,
                    created_at=now,
                )
            )
        return import_row

    def to_schema(self, row: ExternalLapRecordEntity) -> ExternalLapRecord:
        return ExternalLapRecord(
            track=row.track,
            race_class=row.race_class,
            driver=row.driver,
            car=row.car,
            best_lap=row.best_lap,
            best_lap_ms=row.best_lap_ms,
            source="External",
        )
