from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, JSON, String, text
from sqlmodel import Field, SQLModel

from .base import utc_now


class ExtractionRunEntity(SQLModel, table=True):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'running', 'completed', 'failed', 'cancelled')", name="ck_extraction_runs_status_vocab"),
        CheckConstraint("mode IN ('normal', 'dry_run')", name="ck_extraction_runs_mode_vocab"),
        CheckConstraint("workers >= 1", name="ck_extraction_runs_workers"),
        CheckConstraint("total_inputs >= 0", name="ck_extraction_runs_total_inputs"),
        CheckConstraint("to_process >= 0", name="ck_extraction_runs_to_process"),
        CheckConstraint("processed >= 0", name="ck_extraction_runs_processed"),
        CheckConstraint("succeeded >= 0", name="ck_extraction_runs_succeeded"),
        CheckConstraint("failed >= 0", name="ck_extraction_runs_failed"),
        CheckConstraint("skipped >= 0", name="ck_extraction_runs_skipped"),
        CheckConstraint("duplicate_count >= 0", name="ck_extraction_runs_duplicate_count"),
        Index("idx_extraction_runs_status", "status"),
        Index("idx_extraction_runs_created", "created_at"),
    )

    id: str = Field(primary_key=True)
    status: str = Field(default="pending", sa_column_kwargs={"server_default": text("'pending'")})
    mode: str = Field(default="normal", sa_column_kwargs={"server_default": text("'normal'")})
    backend: str = Field(default="lmstudio", sa_column_kwargs={"server_default": text("'lmstudio'")})
    model: str

    prompt_snapshot_id: str | None = Field(
        default=None,
        sa_column=Column(String, ForeignKey("prompt_snapshots.id", ondelete="RESTRICT"), nullable=True),
    )
    prompt_name: str | None = None
    prompt_hash: str | None = None

    input_dir: str | None = None
    workers: int = Field(default=1, sa_column_kwargs={"server_default": text("1")})

    image_format: str | None = None
    max_width: int | None = None
    encode_quality: int | None = None
    grayscale: bool = Field(default=False, sa_column_kwargs={"server_default": text("0")})

    context_length: int | None = None
    reasoning_mode: str | None = None
    eval_batch_size: int | None = None
    physical_batch_size: int | None = None
    flash_attention: bool | None = None
    offload_kv_cache_to_gpu: bool | None = None
    max_completion_tokens: int | None = None
    temperature: float | None = None
    max_retries: int | None = None

    timeout_connect: int | None = None
    timeout_read: int | None = None
    performance_tps_floor: float | None = None
    performance_reload_elapsed_s: float | None = None
    performance_reload_streak: int | None = None

    config_extra_json: str | None = None

    total_inputs: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    to_process: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    processed: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    succeeded: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    failed: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    skipped: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    duplicate_count: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    review_case_count: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})

    operational_error_code: str | None = None
    operational_error_message: str | None = None

    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunInputEntity(SQLModel, table=True):
    __tablename__ = "run_inputs"
    __table_args__ = (
        CheckConstraint("decision IN ('process', 'skip', 'duplicate', 'missing', 'unsupported', 'outside_input', 'hash_failed')", name="ck_run_inputs_decision_vocab"),
        CheckConstraint("duplicate_kind IS NULL OR duplicate_kind IN ('hash', 'batch')", name="ck_run_inputs_duplicate_kind_vocab"),
        CheckConstraint("input_order >= 0", name="ck_run_inputs_order"),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_run_inputs_size_nonnegative"),
        Index("idx_run_inputs_run_decision", "run_id", "decision"),
        Index("idx_run_inputs_process_reason", "run_id", "process_reason"),
        Index("idx_run_inputs_image_file", "image_file_id"),
        Index("idx_run_inputs_hash", "file_hash"),
    )

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(sa_column=Column(String, ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False))
    image_file_id: str | None = Field(
        default=None,
        sa_column=Column(String, ForeignKey("image_files.id", ondelete="SET NULL"), nullable=True),
    )
    input_order: int
    input_path: str
    normalized_path: str | None = None
    file_name: str | None = None
    extension: str | None = None
    file_hash: str | None = None
    size_bytes: int | None = None
    mtime_ns: int | None = None
    decision: str
    process_reason: str | None = None
    skip_reason: str | None = None
    duplicate_kind: str | None = None
    duplicate_of_hash: str | None = None
    duplicate_of_input_id: int | None = Field(
        default=None,
        sa_column=Column(ForeignKey("run_inputs.id", ondelete="SET NULL"), nullable=True),
    )
    created_at: datetime = Field(default_factory=utc_now)


class ModelRuntimeSnapshotEntity(SQLModel, table=True):
    __tablename__ = "model_runtime_snapshots"
    __table_args__ = (
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_runtime_size_nonnegative"),
        Index(
            "idx_runtime_one_preflight_per_run",
            "run_id",
            unique=True,
            sqlite_where=text("snapshot_kind = 'preflight'"),
        ),
        Index("idx_model_runtime_run_kind", "run_id", "snapshot_kind"),
    )

    id: str = Field(primary_key=True)
    run_id: str = Field(sa_column=Column(String, ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False))
    snapshot_kind: str = Field(default="preflight", sa_column_kwargs={"server_default": text("'preflight'")})
    endpoint: str
    configured_model: str | None = None
    matched_model: str | None = None
    loaded_model: str | None = None
    instance_id: str | None = None
    display_name: str | None = None
    publisher: str | None = None
    architecture: str | None = None
    format: str | None = None
    params_string: str | None = None
    quantization: str | None = None
    selected_variant: str | None = None
    size_bytes: int | None = None
    max_context_length: int | None = None
    capabilities_json: dict | None = Field(default=None, sa_column=Column(JSON))
    desired_load_config_json: dict | None = Field(default=None, sa_column=Column(JSON))
    effective_load_config_json: dict | None = Field(default=None, sa_column=Column(JSON))
    load_time_seconds: float | None = None
    health_ok: bool = Field(default=False, sa_column_kwargs={"server_default": text("0")})
    health_message: str | None = None
    model_matches_config: bool | None = None
    captured_at: datetime = Field(default_factory=utc_now)
