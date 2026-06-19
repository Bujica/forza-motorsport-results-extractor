from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, JSON, String, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from .base import utc_now


class LapRecordEntity(SQLModel, table=True):
    __tablename__ = "lap_records"
    __table_args__ = (
        UniqueConstraint("extraction_result_id", "lap_index", name="uq_lap_records_result_index"),
        UniqueConstraint("image_file_id", "run_id", "lap_index", name="uq_lap_records_image_file_run_index"),
        CheckConstraint("lap_index >= 0", name="ck_lap_records_index"),
        CheckConstraint("best_lap_ms >= 0", name="ck_lap_records_best_lap_ms"),
        Index("idx_lap_records_track_class_driver", "track_normalized", "race_class", "driver_normalized"),
        Index("idx_lap_records_track_class_car", "track_normalized", "race_class", "car_normalized"),
        Index(
            "idx_lap_records_best_track_class_driver",
            "track_normalized",
            "race_class",
            "driver_normalized",
            sqlite_where=text("is_best_lap = 1"),
        ),
        Index(
            "idx_lap_records_best_track_class_car",
            "track_normalized",
            "race_class",
            "car_normalized",
            sqlite_where=text("is_best_lap = 1"),
        ),
        Index(
            "idx_lap_records_best_gui_order",
            "track",
            "race_class",
            "weather",
            "best_lap_ms",
            "driver",
            "car",
            sqlite_where=text("is_best_lap = 1"),
        ),
        Index("idx_lap_records_image_file", "image_file_id"),
    )

    id: str = Field(primary_key=True)
    run_id: str = Field(sa_column=Column(String, ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False))
    image_file_id: str = Field(sa_column=Column(String, ForeignKey("image_files.id", ondelete="RESTRICT"), nullable=False))
    extraction_result_id: str = Field(sa_column=Column(String, ForeignKey("extraction_results.id", ondelete="CASCADE"), nullable=False))
    lap_index: int
    source_file: str = Field(default="", sa_column_kwargs={"server_default": text("''")})
    driver: str = Field(default="", sa_column_kwargs={"server_default": text("''")})
    driver_normalized: str = Field(default="", sa_column_kwargs={"server_default": text("''")})
    car: str = Field(default="", sa_column_kwargs={"server_default": text("''")})
    car_normalized: str = Field(default="", sa_column_kwargs={"server_default": text("''")})
    race_class: str = Field(default="", sa_column_kwargs={"server_default": text("''")})
    track: str = Field(default="", sa_column_kwargs={"server_default": text("''")})
    track_normalized: str = Field(default="", sa_column_kwargs={"server_default": text("''")})
    weather: str = Field(default="unknown", sa_column_kwargs={"server_default": text("'unknown'")})
    temp_f: float | None = None
    temp_c: float | None = None
    best_lap: str = Field(default="", sa_column_kwargs={"server_default": text("''")})
    best_lap_ms: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    dirty: bool = Field(default=False, sa_column_kwargs={"server_default": text("0")})
    raw_lap_json: dict | None = Field(default=None, sa_column=Column(JSON))
    is_best_lap: bool = Field(default=False, sa_column_kwargs={"server_default": text("0")})
    created_at: datetime = Field(default_factory=utc_now)
