from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, JSON, String, text
from sqlmodel import Field, SQLModel

from .base import utc_now


class ImageFileEntity(SQLModel, table=True):
    __tablename__ = "image_files"
    __table_args__ = (
        CheckConstraint("file_status IN ('available', 'missing')", name="ck_image_files_file_status_vocab"),
        CheckConstraint("best_lap_status IN ('pending', 'contributing', 'non_contributing')", name="ck_image_files_best_lap_status_vocab"),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_image_files_size_nonnegative"),
        CheckConstraint("width_px IS NULL OR width_px > 0", name="ck_image_files_width_positive"),
        CheckConstraint("height_px IS NULL OR height_px > 0", name="ck_image_files_height_positive"),
        Index("idx_image_files_hash", "file_hash"),
        Index("idx_image_files_status", "file_status"),
        Index("idx_image_files_best_lap_status", "best_lap_status"),
        Index("idx_image_files_duplicate_of", "duplicate_of_image_file_id"),
        Index("idx_image_files_file_modified_at", "file_modified_at"),
    )

    id: str = Field(primary_key=True)
    file_hash: str
    duplicate_of_image_file_id: str | None = Field(
        default=None,
        sa_column=Column(String, ForeignKey("image_files.id", ondelete="SET NULL"), nullable=True),
    )
    size_bytes: int | None = None

    width_px: int | None = None
    height_px: int | None = None
    bit_depth: int | None = None
    color_mode: str | None = None
    mime_type: str | None = None
    image_format: str | None = None
    image_metadata_json: dict = Field(default_factory=dict, sa_column=Column(JSON))

    current_name: str | None = None
    current_path: str | None = None
    semantic_name: str | None = None

    file_modified_at: datetime | None = None

    race_datetime: datetime | None = None
    race_date: date | None = None
    race_datetime_source: str = Field(default="file_modified_at", sa_column_kwargs={"server_default": text("'file_modified_at'")})

    file_status: str = Field(default="available", sa_column_kwargs={"server_default": text("'available'")})
    best_lap_status: str = Field(default="pending", sa_column_kwargs={"server_default": text("'pending'")})

    first_seen_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime | None = None
    missing_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
