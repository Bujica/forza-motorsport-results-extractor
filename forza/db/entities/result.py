from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, JSON, String, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from .base import utc_now


class ExtractionResultEntity(SQLModel, table=True):
    __tablename__ = "extraction_results"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'running', 'ok', 'error', 'cancelled')", name="ck_extraction_results_status_vocab"),
        UniqueConstraint("run_id", "image_file_id", name="uq_extraction_results_run_image"),
        UniqueConstraint("run_input_id", name="uq_extraction_results_run_input"),
        CheckConstraint("attempt_count >= 0", name="ck_extraction_results_attempt_count"),
        CheckConstraint("request_image_width IS NULL OR request_image_width > 0", name="ck_extraction_results_image_width"),
        CheckConstraint("request_image_height IS NULL OR request_image_height > 0", name="ck_extraction_results_image_height"),
        CheckConstraint("request_image_bytes IS NULL OR request_image_bytes >= 0", name="ck_extraction_results_image_bytes"),
        Index("idx_extraction_results_status", "status"),
        Index("idx_extraction_results_image_file", "image_file_id"),
    )

    id: str = Field(primary_key=True)
    run_id: str = Field(sa_column=Column(String, ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False))
    run_input_id: int = Field(sa_column=Column(ForeignKey("run_inputs.id", ondelete="CASCADE"), nullable=False))
    image_file_id: str = Field(sa_column=Column(String, ForeignKey("image_files.id", ondelete="RESTRICT"), nullable=False))
    status: str
    error_type: str | None = None
    error_message: str | None = None
    accepted_attempt_id: str | None = Field(
        default=None,
        sa_column=Column(String, ForeignKey("extraction_attempts.id", ondelete="RESTRICT"), nullable=True),
    )
    attempt_count: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    model: str | None = None
    model_instance_id: str | None = None
    prompt_snapshot_id: str | None = Field(
        default=None,
        sa_column=Column(String, ForeignKey("prompt_snapshots.id", ondelete="RESTRICT"), nullable=True),
    )
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    tokens_per_second: float | None = None
    time_to_first_token_s: float | None = None
    model_load_time_s: float | None = None
    request_image_format: str | None = None
    request_image_mime_type: str | None = None
    request_image_width: int | None = None
    request_image_height: int | None = None
    request_image_bytes: int | None = None
    duration_ms: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime | None = None


class ExtractionAttemptEntity(SQLModel, table=True):
    __tablename__ = "extraction_attempts"
    __table_args__ = (
        CheckConstraint("status IN ('ok', 'error', 'cancelled')", name="ck_extraction_attempts_status_vocab"),
        UniqueConstraint("extraction_result_id", "attempt_number", name="uq_extraction_attempts_result_attempt"),
        CheckConstraint(
            "(accepted = 1 AND status = 'ok') OR (accepted = 0 AND status <> 'ok')",
            name="ck_attempt_acceptance_status",
        ),
        CheckConstraint("attempt_number >= 1", name="ck_attempt_number_positive"),
        CheckConstraint("request_image_width IS NULL OR request_image_width > 0", name="ck_attempt_image_width"),
        CheckConstraint("request_image_height IS NULL OR request_image_height > 0", name="ck_attempt_image_height"),
        CheckConstraint("request_image_bytes IS NULL OR request_image_bytes >= 0", name="ck_attempt_image_bytes"),
        Index(
            "idx_attempts_one_accepted_per_result",
            "extraction_result_id",
            unique=True,
            sqlite_where=text("accepted = 1"),
        ),
        Index("idx_attempts_run_status", "run_id", "status"),
        Index("idx_attempts_reason", "attempt_reason"),
    )

    id: str = Field(primary_key=True)
    extraction_result_id: str = Field(sa_column=Column(String, ForeignKey("extraction_results.id", ondelete="CASCADE"), nullable=False))
    run_id: str = Field(sa_column=Column(String, ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False))
    image_file_id: str = Field(sa_column=Column(String, ForeignKey("image_files.id", ondelete="RESTRICT"), nullable=False))
    runtime_snapshot_id: str | None = Field(
        default=None,
        sa_column=Column(String, ForeignKey("model_runtime_snapshots.id", ondelete="SET NULL"), nullable=True),
    )
    attempt_number: int
    attempt_reason: str = Field(default="initial")
    status: str
    accepted: bool = Field(default=False, sa_column_kwargs={"server_default": text("0")})
    rejected_reason: str | None = None
    http_status: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    model: str | None = None
    model_instance_id: str | None = None
    request_image_format: str | None = None
    request_image_mime_type: str | None = None
    request_image_width: int | None = None
    request_image_height: int | None = None
    request_image_bytes: int | None = None
    context_length: int | None = None
    reasoning_mode: str | None = None
    request_config_json: dict | None = Field(default=None, sa_column=Column(JSON))
    request_messages_json: dict | list | None = Field(default=None, sa_column=Column(JSON))
    request_hash: str | None = None
    retry_instruction_text: str | None = None
    raw_response: str | None = None
    parsed_json: dict | None = Field(default=None, sa_column=Column(JSON))
    parse_error: str | None = None
    validation_status: str | None = None
    validation_issues_json: list = Field(default_factory=list, sa_column=Column(JSON))
    response_stats_json: dict | None = Field(default=None, sa_column=Column(JSON))
    model_load_config_json: dict | None = Field(default=None, sa_column=Column(JSON))
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    time_to_first_token_s: float | None = None
    duration_ms: int | None = None
    tokens_per_second: float | None = None
    model_load_time_s: float | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ModelArtifactEntity(SQLModel, table=True):
    __tablename__ = "model_artifacts"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="ck_model_artifacts_size_nonnegative"),
        Index("idx_model_artifacts_run_image_file", "run_id", "image_file_id"),
        Index("idx_model_artifacts_attempt", "attempt_id"),
    )

    id: str = Field(primary_key=True)
    run_id: str = Field(sa_column=Column(String, ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False))
    image_file_id: str | None = Field(
        default=None,
        sa_column=Column(String, ForeignKey("image_files.id", ondelete="SET NULL"), nullable=True),
    )
    extraction_result_id: str | None = Field(
        default=None,
        sa_column=Column(String, ForeignKey("extraction_results.id", ondelete="CASCADE"), nullable=True),
    )
    attempt_id: str | None = Field(
        default=None,
        sa_column=Column(String, ForeignKey("extraction_attempts.id", ondelete="CASCADE"), nullable=True),
    )
    artifact_type: str
    file_path: str
    relative_path: str | None = None
    sha256: str
    size_bytes: int
    media_type: str | None = None
    is_canonical: bool = Field(default=False, sa_column_kwargs={"server_default": text("0")})
    created_at: datetime = Field(default_factory=utc_now)
