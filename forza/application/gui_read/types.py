from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GuiImage:
    id: str
    file_hash: str
    duplicate_of_image_file_id: str | None = None
    current_name: str | None = None
    semantic_name: str | None = None
    current_path: str | None = None
    file_status: str = "available"
    processing_status: str = "unprocessed"
    best_lap_status: str = "pending"
    file_size_bytes: int | None = None
    image_format: str | None = None
    mime_type: str | None = None
    width_px: int | None = None
    height_px: int | None = None
    bit_depth: int | None = None
    color_mode: str | None = None
    file_modified_at: object | None = None
    race_datetime: object | None = None
    race_date: object | None = None
    race_datetime_source: str = "file_modified_at"
    image_metadata_json: dict[str, Any] | None = None


@dataclass(frozen=True)
class GuiLap:
    id: str
    image_file_id: str
    extraction_result_id: str
    run_id: str
    source_file: str
    lap_index: int
    track: str
    race_class: str
    weather: str
    temp_f: float | None
    driver: str
    car: str
    car_class: str
    best_lap: str
    best_lap_ms: int
    dirty: bool
    is_best_lap: bool
    race_datetime: object | None = None
    race_date: object | None = None
    image_format: str | None = None


@dataclass(frozen=True)
class GuiExtractionResult:
    id: str
    run_id: str
    image_file_id: str
    status: str
    error_message: str | None
    backend: str | None
    model: str | None
    prompt_name: str | None
    raw_response_artifact_path: str | None
    has_raw_response: bool
    has_parsed_result: bool
    raw_response: str | None = None
    raw_response_payload: dict[str, Any] | None = None
    parsed_result_payload: dict[str, Any] | None = None
    created_at: object | None = None


@dataclass(frozen=True)
class GuiExtractionAttempt:
    id: str
    extraction_result_id: str
    attempt_number: int
    attempt_reason: str
    status: str
    accepted: bool
    rejected_reason: str | None
    model: str | None
    model_instance_id: str | None
    context_length: int | None
    reasoning_mode: str | None
    duration_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    tokens_per_second: float | None
    parse_error: str | None
    validation_status: str | None
    validation_issues_json: list[str]
    created_at: object | None


@dataclass(frozen=True)
class GuiImageDebugSummary:
    image_file_id: str
    image_name: str
    race_date: object | None
    file_status: str
    processing_status: str
    best_lap_status: str
    latest_result_id: str | None
    latest_result_status: str | None
    run_id: str | None
    run_label: str | None
    backend: str | None
    model: str | None
    prompt_name: str | None
    attempt_count: int
    lap_count: int
    review_count: int
    artifact_count: int
    created_at: object | None


GuiImageDebugCase = GuiImageDebugSummary


@dataclass(frozen=True)
class GuiImageDebugExtraction:
    id: str
    run_id: str
    run_label: str
    status: str
    backend: str | None
    model: str | None
    prompt_name: str | None
    accepted_attempt_id: str | None
    attempt_count: int
    duration_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    error_type: str | None
    error_message: str | None
    request_image_format: str | None
    request_image_mime_type: str | None
    request_image_width: int | None
    request_image_height: int | None
    request_image_bytes: int | None
    created_at: object | None


@dataclass(frozen=True)
class GuiImageDebugAttempt:
    id: str
    extraction_result_id: str
    runtime_snapshot_id: str | None
    attempt_number: int
    attempt_reason: str
    status: str
    accepted: bool
    rejected_reason: str | None
    http_status: int | None
    error_code: str | None
    error_message: str | None
    model: str | None
    model_instance_id: str | None
    context_length: int | None
    reasoning_mode: str | None
    duration_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    tokens_per_second: float | None
    parse_error: str | None
    validation_status: str | None
    validation_issues_json: list[str]
    request_config_json: dict[str, Any] | None
    request_messages_json: dict[str, Any] | list[Any] | None
    response_stats_json: dict[str, Any] | None
    model_load_config_json: dict[str, Any] | None
    created_at: object | None


@dataclass(frozen=True)
class GuiImageDebugArtifact:
    id: str
    artifact_type: str
    extraction_result_id: str | None
    attempt_id: str | None
    file_path: str
    relative_path: str | None
    sha256: str
    size_bytes: int
    media_type: str | None
    is_canonical: bool
    created_at: object | None


@dataclass(frozen=True)
class GuiImageDebugRuntime:
    id: str
    run_id: str
    snapshot_kind: str
    endpoint: str
    configured_model: str | None
    matched_model: str | None
    loaded_model: str | None
    instance_id: str | None
    display_name: str | None
    publisher: str | None
    architecture: str | None
    format: str | None
    params_string: str | None
    quantization: str | None
    selected_variant: str | None
    size_bytes: int | None
    max_context_length: int | None
    capabilities_json: dict[str, Any] | None
    desired_load_config_json: dict[str, Any] | None
    effective_load_config_json: dict[str, Any] | None
    load_time_seconds: float | None
    health_ok: bool
    health_message: str | None
    model_matches_config: bool | None
    captured_at: object | None


@dataclass(frozen=True)
class GuiImageDebugLap:
    id: str
    extraction_result_id: str
    run_id: str
    lap_index: int
    track: str
    race_class: str
    driver: str
    car: str
    best_lap: str
    dirty: bool
    is_best_lap: bool


@dataclass(frozen=True)
class GuiImageDebugReview:
    id: str
    case_number: int
    extraction_result_id: str | None
    lap_record_id: str | None
    status: str
    reason: str
    outcome: str
    trigger: str | None
    decision_field: str | None
    model_value: str | None
    corrected_value: str | None
    current_track: str | None
    current_race_class: str | None
    current_best_lap: str | None
    created_at: object | None
    resolved_at: object | None


@dataclass(frozen=True)
class GuiImageDebugDetail:
    image: GuiImage
    cases: list[GuiImageDebugCase]
    results: list[GuiImageDebugExtraction]
    selected_result_id: str | None
    attempts: list[GuiImageDebugAttempt]
    artifacts: list[GuiImageDebugArtifact]
    runtime_snapshots: list[GuiImageDebugRuntime]
    laps: list[GuiImageDebugLap]
    reviews: list[GuiImageDebugReview]
    raw_response: str | None
    raw_response_payload: dict[str, Any] | None
    parsed_result_payload: dict[str, Any] | None
    timeline: list[str]


@dataclass(frozen=True)
class GuiReviewCase:
    id: str
    case_number: int
    business_key: str
    image_file_id: str | None
    run_id: str | None
    extraction_result_id: str | None
    lap_record_id: str | None
    source_file: str
    reason: str
    trigger: str | None
    outcome: str
    decision_field: str | None
    model_value: str | None
    corrected_value: str | None
    error_type: str | None
    track: str
    race_class: str
    weather: str
    temp_f: float | None
    driver: str | None
    car: str | None
    best_lap: str | None
    current_track: str | None
    current_race_class: str | None
    current_weather: str | None
    current_driver: str | None
    current_car: str | None
    current_best_lap: str | None
    current_dirty: bool | None
    status: str
    resolution_note: str | None
    track_suggestions: list[str]
    created_at: object | None
    resolved_at: object | None



@dataclass(frozen=True)
class DashboardSummary:
    images: int
    available_images: int
    missing_images: int
    best_lap_images: int
    review_open: int
    runs: int
    extraction_results: int
    lap_records: int
    best_laps: int


@dataclass(frozen=True)
class GuiRunOption:
    id: str
    label: str
