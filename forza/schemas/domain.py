from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field, TypeAdapter
from pydantic.dataclasses import dataclass

from .enums import (
    AttemptStatus,
    BestLapStatus,
    ExtractionStatus,
    RaceClass,
    ReviewDecisionField,
    ReviewOutcome,
    ReviewReason,
    ReviewTrigger,
    RunStatus,
    ImageFileStatus,
    WeatherType,
)


_PYDANTIC_DATACLASS_CONFIG = ConfigDict(
    arbitrary_types_allowed=True,
    extra="ignore",
    validate_assignment=True,
)


@dataclass(config=_PYDANTIC_DATACLASS_CONFIG)
class LapRecord:
    """A single driver's best-lap result within one race session."""

    driver: str
    car: str
    car_class: str
    best_lap: str
    best_lap_ms: int
    dirty: bool = False


@dataclass(config=_PYDANTIC_DATACLASS_CONFIG)
class RaceSession:
    """Complete race result extracted from one screenshot."""

    track: str
    temp_f: float | None
    temp_c: float | None
    entries: list[LapRecord]
    race_class: RaceClass
    weather: WeatherType = WeatherType.UNKNOWN


@dataclass(config=_PYDANTIC_DATACLASS_CONFIG)
class ImageMetadata:
    """Physical metadata captured from the image file."""

    file_size_bytes: int | None = None
    image_format: str | None = None
    mime_type: str | None = None
    width_px: int | None = None
    height_px: int | None = None
    bit_depth: int | None = None
    color_mode: str | None = None
    file_modified_at: datetime | None = None
    race_datetime: datetime | None = None
    race_date: date | None = None
    race_datetime_source: str = "file_modified_at"
    image_metadata_json: dict = Field(default_factory=dict)


@dataclass(config=_PYDANTIC_DATACLASS_CONFIG)
class ModelRequestMetadata:
    """Metadata describing the concrete request sent to an LLM endpoint."""

    endpoint_url: str | None = None
    request_image_format: str | None = None
    request_image_mime_type: str | None = None
    request_image_width_px: int | None = None
    request_image_height_px: int | None = None
    request_image_bytes: int | None = None
    context_length: int | None = None
    reasoning_mode: str | None = None
    request_config_json: dict | None = None
    model_load_config_json: dict | None = None


@dataclass(config=_PYDANTIC_DATACLASS_CONFIG)
class ModelResponseStats:
    """Backend response metrics retained for API/model comparisons."""

    duration_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    tokens_per_second: float | None = None
    time_to_first_token_seconds: float | None = None
    model_load_time_seconds: float | None = None
    response_stats_json: dict | None = None


@dataclass(config=_PYDANTIC_DATACLASS_CONFIG)
class ModelExtractionAttempt:
    """One concrete model request made while extracting an image file."""

    attempt_number: int
    attempt_reason: str = "initial"
    status: AttemptStatus = AttemptStatus.ERROR
    accepted: bool = False
    rejected_reason: str | None = None
    runtime_snapshot_id: str | None = None
    endpoint_url: str | None = None
    model: str | None = None
    model_instance_id: str | None = None
    request_image_format: str | None = None
    request_image_mime_type: str | None = None
    request_image_width_px: int | None = None
    request_image_height_px: int | None = None
    request_image_bytes: int | None = None
    context_length: int | None = None
    reasoning_mode: str | None = None
    request_config_json: dict | None = None
    request_messages_json: list[dict] | None = None
    request_hash: str | None = None
    model_load_config_json: dict | None = None
    duration_ms: int | None = None
    http_status: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    retry_instruction_text: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    tokens_per_second: float | None = None
    time_to_first_token_seconds: float | None = None
    model_load_time_seconds: float | None = None
    raw_response: str | None = None
    parsed_json: dict | None = None
    parse_error: str | None = None
    validation_status: str | None = None
    validation_issues_json: list[str] = Field(default_factory=list)
    response_stats_json: dict | None = None
    artifact_path: str | None = None
    artifact_type: str | None = None
    artifact_is_canonical: bool = False


@dataclass(config=_PYDANTIC_DATACLASS_CONFIG)
class ExtractionResult:
    """
    Canonical extraction result for one immutable image file.

    ``image_file_id`` and ``extraction_result_id`` are set by DatabaseService.
    ``raw_response`` carries the exact model text before parse/repair.
    ``raw_response_payload`` carries the parsed LLM output for relational storage
    and debug/prompt-comparison screens.
    ``raw_response_artifact_path`` points to the on-disk debug file written to disk by the
    backend. ``model_response_stats`` carries backend metrics used by diagnostics
    and model-output comparison.
    """

    source_file: str
    file_hash: str
    session: RaceSession | None
    status: ExtractionStatus = ExtractionStatus.ERROR
    image_file_id: str | None = None
    run_id: str | None = None
    extraction_result_id: str | None = None
    semantic_name: str | None = None
    error: str | None = None
    current_path: str | None = None
    raw_response: str | None = None
    raw_response_payload: dict | None = None
    raw_response_artifact_path: str | None = None
    model_backend: str | None = None
    model_name: str | None = None
    model_prompt_name: str | None = None
    model_request: ModelRequestMetadata | None = None
    model_response_stats: ModelResponseStats | None = None
    model_attempts: list[ModelExtractionAttempt] = Field(default_factory=list)


@dataclass(config=_PYDANTIC_DATACLASS_CONFIG)
class ReviewCase:
    reason: ReviewReason
    source_file: str
    track: str
    race_class: RaceClass
    weather: WeatherType
    temp_f: float | None
    driver: str | None
    car: str | None
    best_lap: str | None
    case_number: int = 0
    image_file_id: str | None = None
    run_id: str | None = None
    extraction_result_id: str | None = None
    lap_record_id: str | None = None
    lap_index: int | None = None
    trigger: ReviewTrigger | None = None
    model_value: str | None = None
    outcome: ReviewOutcome = ReviewOutcome.PENDING
    decision_field: ReviewDecisionField | None = None
    corrected_value: str | None = None
    error_type: str | None = None
    track_suggestions: list[str] = Field(default_factory=list)


@dataclass(config=_PYDANTIC_DATACLASS_CONFIG)
class ImageFile:
    """Domain schema for an observed image file.

    ``current_name`` and ``current_path`` are the authoritative physical file
    name and path.
    """

    id: str
    file_hash: str
    duplicate_of_image_file_id: str | None = None
    current_name: str | None = None
    semantic_name: str | None = None
    current_path: str | None = None
    file_status: ImageFileStatus = ImageFileStatus.AVAILABLE
    best_lap_status: BestLapStatus = BestLapStatus.PENDING
    file_size_bytes: int | None = None
    image_format: str | None = None
    mime_type: str | None = None
    width_px: int | None = None
    height_px: int | None = None
    bit_depth: int | None = None
    color_mode: str | None = None
    file_modified_at: datetime | None = None
    race_datetime: datetime | None = None
    race_date: date | None = None
    race_datetime_source: str = "file_modified_at"
    image_metadata_json: dict = Field(default_factory=dict)


@dataclass(config=_PYDANTIC_DATACLASS_CONFIG)
class ExtractionRun:
    """Schema representation of a complete extraction run lifecycle."""

    id: str
    model: str
    backend: str
    prompt_name: str = ""
    status: RunStatus = RunStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    review_case_count: int = 0
    input_dir: str | None = None
    run_config: dict[str, Any] = Field(default_factory=dict)
    operational_error_message: str | None = None


@dataclass(config=_PYDANTIC_DATACLASS_CONFIG)
class ExportArtifact:
    path: Path
    format: str
    run_id: str | None = None


@dataclass(config=_PYDANTIC_DATACLASS_CONFIG)
class ExportLap:
    """Flat row used by CSV/PDF export and SQL-native read paths."""

    image_file_id: str
    source_file: str
    file_hash: str | None
    lap_index: int
    semantic_name: str | None
    race_datetime: datetime | None
    race_date: date | None
    image_format: str | None
    width_px: int | None
    height_px: int | None
    track: str
    race_class: str
    weather: str
    temp_f: float | None
    temp_c: float | None
    driver: str
    car: str
    car_class: str
    best_lap: str
    best_lap_ms: int
    dirty: bool
    is_best_lap: bool


@dataclass(config=_PYDANTIC_DATACLASS_CONFIG)
class ExternalLapRecord:
    track: str
    race_class: str
    driver: str
    car: str
    best_lap: str
    best_lap_ms: int
    source: str = "External"


def dump_schema(value: Any) -> Any:
    """Serialize a Pydantic dataclass or container to JSON-compatible Python."""
    return TypeAdapter(type(value)).dump_python(value, mode="json")


def validate_schema(schema_type: type, data: Any) -> Any:
    """Validate raw Python data into the requested schema type."""
    return TypeAdapter(schema_type).validate_python(data)
