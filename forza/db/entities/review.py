from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, JSON, String, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from .base import utc_now


class ReviewCaseEntity(SQLModel, table=True):
    __tablename__ = "review_cases"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'resolved', 'ignored', 'auto_resolved')", name="ck_review_cases_status_vocab"),
        CheckConstraint("outcome IN ('pending', 'confirmed', 'model_error', 'ignored')", name="ck_review_cases_outcome_vocab"),
        CheckConstraint("\"trigger\" IS NULL OR \"trigger\" IN ('model_marked_dirty', 'weather_unknown', 'rain_time_suspicious', 'track_unknown', 'track_unresolved', 'track_not_in_reference', 'class_unknown', 'class_invalid', 'car_empty', 'car_not_in_reference', 'driver_name_empty', 'numeric_prefix', 'invalid_symbol')", name="ck_review_cases_trigger_vocab"),
        CheckConstraint("decision_field IS NULL OR decision_field IN ('dirty', 'track', 'weather', 'race_class', 'car', 'driver')", name="ck_review_cases_decision_field_vocab"),
        CheckConstraint("reason IN ('dirty_lap', 'track', 'weather', 'race_class', 'car', 'driver_name')", name="ck_review_cases_reason_vocab"),
        UniqueConstraint("business_key", name="uq_review_cases_business_key"),
        UniqueConstraint("case_number", name="uq_review_cases_case_number"),
        Index("idx_review_cases_status_reason", "status", "reason"),
    )

    id: str = Field(primary_key=True)
    run_id: str | None = Field(default=None, sa_column=Column(String, ForeignKey("extraction_runs.id", ondelete="SET NULL"), nullable=True))
    image_file_id: str | None = Field(default=None, sa_column=Column(String, ForeignKey("image_files.id", ondelete="RESTRICT"), nullable=True))
    extraction_result_id: str | None = Field(default=None, sa_column=Column(String, ForeignKey("extraction_results.id", ondelete="SET NULL"), nullable=True))
    lap_record_id: str | None = Field(default=None, sa_column=Column(String, ForeignKey("lap_records.id", ondelete="SET NULL"), nullable=True))
    case_number: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    source_file: str = Field(default="", sa_column_kwargs={"server_default": text("''")})
    weather: str = Field(default="unknown", sa_column_kwargs={"server_default": text("'unknown'")})
    temp_f: float | None = None
    status: str = Field(default="open", sa_column_kwargs={"server_default": text("'open'")})
    reason: str
    trigger: str | None = None
    outcome: str = Field(default="pending", sa_column_kwargs={"server_default": text("'pending'")})
    decision_field: str | None = None
    model_value: str | None = None
    corrected_value: str | None = None
    error_type: str | None = None
    business_key: str = Field(default_factory=lambda: uuid4().hex)
    driver: str | None = None
    driver_normalized: str | None = None
    track: str | None = None
    track_normalized: str | None = None
    race_class: str | None = None
    car: str | None = None
    car_normalized: str | None = None
    lap_index: int | None = None
    best_lap: str | None = None
    message: str | None = None
    track_suggestions_json: list | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_note: str | None = None


class ReviewCorrectionEntity(SQLModel, table=True):
    __tablename__ = "review_corrections"
    __table_args__ = (
        CheckConstraint("field IN ('dirty', 'track', 'weather', 'race_class', 'car', 'driver')", name="ck_review_corrections_field_vocab"),
        CheckConstraint("cause IN ('review', 'rebuild', 'auto', 'unknown')", name="ck_review_corrections_cause_vocab"),
        UniqueConstraint("stable_key", name="uq_review_corrections_stable_key"),
        Index("idx_review_corrections_image_file_field", "image_file_id", "field"),
    )

    id: str = Field(primary_key=True)
    stable_key: str
    image_file_id: str = Field(sa_column=Column(String, ForeignKey("image_files.id", ondelete="RESTRICT"), nullable=False))
    lap_index: int | None = None
    field: str
    model_value: str | None = None
    corrected_value: str
    error_type: str | None = None
    cause: str = Field(default="unknown", sa_column_kwargs={"server_default": text("'unknown'")})
    review_case_id: str | None = Field(default=None, sa_column=Column(String, ForeignKey("review_cases.id", ondelete="SET NULL"), nullable=True))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ImageFlagEntity(SQLModel, table=True):
    __tablename__ = "image_flags"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'resolved', 'ignored')", name="ck_image_flags_status_vocab"),
        CheckConstraint("flag_scope IN ('image', 'lap')", name="ck_image_flags_scope_vocab"),
        CheckConstraint("flag_type IN ('duplicate', 'dirty_lap', 'track', 'weather', 'race_class', 'car', 'driver_name')", name="ck_image_flags_flag_type_vocab"),
        UniqueConstraint("flag_key", name="uq_image_flags_flag_key"),
        Index("idx_image_flags_image_file_type_status", "image_file_id", "flag_type", "status"),
    )

    id: str = Field(primary_key=True)
    image_file_id: str = Field(sa_column=Column(String, ForeignKey("image_files.id", ondelete="RESTRICT"), nullable=False))
    run_id: str | None = Field(default=None, sa_column=Column(String, ForeignKey("extraction_runs.id", ondelete="SET NULL"), nullable=True))
    extraction_result_id: str | None = Field(default=None, sa_column=Column(String, ForeignKey("extraction_results.id", ondelete="SET NULL"), nullable=True))
    lap_record_id: str | None = Field(default=None, sa_column=Column(String, ForeignKey("lap_records.id", ondelete="SET NULL"), nullable=True))
    flag_key: str = Field(default_factory=lambda: uuid4().hex)
    flag_scope: str = Field(default="image", sa_column_kwargs={"server_default": text("'image'")})
    lap_index: int | None = None
    driver_normalized: str | None = None
    track_normalized: str | None = None
    race_class: str | None = None
    flag_type: str = Field(default="")
    status: str = Field(default="active", sa_column_kwargs={"server_default": text("'active'")})
    created_by: str = Field(default="system", sa_column_kwargs={"server_default": text("'system'")})
    reason: str | None = None
    note: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None
