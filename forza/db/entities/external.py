from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, JSON, String, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from .base import utc_now


class ExternalRecordImportEntity(SQLModel, table=True):
    __tablename__ = "external_record_imports"
    __table_args__ = (
        CheckConstraint("status IN (\'pending\', \'active\', \'failed\')", name="ck_external_record_imports_status_vocab"),
        CheckConstraint("total_rows >= 0", name="ck_external_record_imports_total_rows"),
        CheckConstraint("accepted_rows >= 0", name="ck_external_record_imports_accepted_rows"),
        CheckConstraint("rejected_rows >= 0", name="ck_external_record_imports_rejected_rows"),
        CheckConstraint("issue_count >= 0", name="ck_external_record_imports_issue_count"),
    )

    id: str = Field(primary_key=True)
    source_path: str
    source_hash: str | None = None
    status: str = Field(default="pending")
    active: bool = Field(default=False)
    total_rows: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    accepted_rows: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    rejected_rows: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    issue_count: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    issues_json: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    imported_at: datetime | None = None
    activated_at: datetime | None = None


class ExternalLapRecordEntity(SQLModel, table=True):
    __tablename__ = "external_lap_records"
    __table_args__ = (
        CheckConstraint("weather IN (\'dry\', \'rain\', \'unknown\')", name="ck_external_lap_records_weather_vocab"),
        CheckConstraint("best_lap_ms >= 0", name="ck_external_lap_records_best_lap_ms"),
        Index(
            "idx_external_lap_records_active_order",
            "track",
            "race_class",
            "best_lap_ms",
            sqlite_where=text("active = 1"),
        ),
    )

    id: str = Field(primary_key=True)
    import_id: str = Field(sa_column=Column(String, ForeignKey("external_record_imports.id", ondelete="CASCADE"), nullable=False))
    track: str
    track_normalized: str | None = None
    race_class: str
    driver: str
    driver_normalized: str | None = None
    car: str
    car_normalized: str | None = None
    weather: str = Field(default="unknown")
    best_lap: str
    best_lap_ms: int = Field(default=0)
    active: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)
