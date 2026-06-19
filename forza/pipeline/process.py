from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from ..config import AppConfig
from ..lmstudio import LLMBackend, ExtractionError, LMSTUDIO_BACKEND_NAME, ModelExtractionResult
from .image import encode_image_payload, semantic_filename
from ..domain.lap import (
    parse_lap_time_ms, is_dirty_lap,
    extract_class_letter, detect_race_class,
    fahrenheit_to_celsius, sanitize_driver_name, normalize_weather,
)
from ..schemas import ExtractionResult, LapRecord, ModelExtractionAttempt, ModelRequestMetadata, RaceSession
from ..domain.normalizer import ReferenceData, fix_car_name, fix_track_name


log = logging.getLogger("forza")

_AMBIGUOUS_TRACK = "Unknown (ambiguous layout)"


def build_semantic_name(filename: str, track: str, race_class: str) -> str:
    """Build a semantic filename without moving or renaming the file."""
    return semantic_filename(track, race_class, Path(filename).suffix)




def process_image(
    filename: str,
    hash_value: str,
    image_path: Path,
    backend: LLMBackend,
    refs: ReferenceData,
    cfg: AppConfig,
    run_id: str,
) -> ExtractionResult:
    """
    Process one screenshot end-to-end and return an ExtractionResult.
    """
    raw_base = hash_value[:16]
    raw_anchor = f"{raw_base}{Path(filename).suffix}"

    encoded = encode_image_payload(
        image_path,
        max_width=cfg.image.max_width,
        encode_quality=cfg.image.encode_quality,
        fmt=cfg.llm.image_format,
        grayscale=cfg.image.grayscale,
    )
    request_metadata = encoded.request_metadata(endpoint_url=cfg.llm.url)
    request_metadata = replace(
        request_metadata,
        context_length=getattr(cfg.llm, "context_length", None),
        reasoning_mode=getattr(cfg.llm, "reasoning_mode", None),
        request_config_json={
            "temperature": cfg.llm.temperature,
            "max_output_tokens": cfg.llm.max_completion_tokens,
            "context_length": getattr(cfg.llm, "context_length", None),
            "reasoning_mode": getattr(cfg.llm, "reasoning_mode", None),
            "image_format": cfg.llm.image_format,
            "max_width": cfg.image.max_width,
            "encode_quality": cfg.image.encode_quality,
            "grayscale": cfg.image.grayscale,
        },
    )
    set_request_context = getattr(backend, "set_request_context", None)
    if callable(set_request_context):
        set_request_context(request_metadata)

    try:
        backend_output = backend.extract(
            encoded.data_b64,
            encoded.mime_type,
            semantic_name=raw_anchor,
            run_id=run_id,
            file_hash=hash_value,
        )
        if not isinstance(backend_output, ModelExtractionResult):
            raise TypeError("LLMBackend.extract() must return ModelExtractionResult")
        raw = backend_output.parsed
        raw_response = backend_output.raw_response
        backend_raw_response_artifact_path = backend_output.raw_response_artifact_path
        response_stats = backend_output.response_stats
        model_attempts = backend_output.attempts or []
        if backend_output.request_metadata is not None:
            request_metadata = replace(
                backend_output.request_metadata,
                request_image_format=request_metadata.request_image_format,
                request_image_mime_type=request_metadata.request_image_mime_type,
                request_image_width_px=request_metadata.request_image_width_px,
                request_image_height_px=request_metadata.request_image_height_px,
                request_image_bytes=request_metadata.request_image_bytes,
                request_config_json=request_metadata.request_config_json,
            )
        model_attempts = [
            replace(
                attempt,
                request_image_format=request_metadata.request_image_format,
                request_image_mime_type=request_metadata.request_image_mime_type,
                request_image_width_px=request_metadata.request_image_width_px,
                request_image_height_px=request_metadata.request_image_height_px,
                request_image_bytes=request_metadata.request_image_bytes,
            )
            for attempt in model_attempts
        ]
    except ExtractionError as exc:
        model_attempts = getattr(exc, "attempts", [])
        model_attempts = [
            replace(
                attempt,
                request_image_format=request_metadata.request_image_format,
                request_image_mime_type=request_metadata.request_image_mime_type,
                request_image_width_px=request_metadata.request_image_width_px,
                request_image_height_px=request_metadata.request_image_height_px,
                request_image_bytes=request_metadata.request_image_bytes,
            )
            for attempt in model_attempts
        ]
        log.error(f"[pipeline] {filename}: {exc}")
        return ExtractionResult(
            source_file=filename,
            file_hash=hash_value,
            session=None,
            status="error",
            error=str(exc),
            model_backend=LMSTUDIO_BACKEND_NAME,
            model_name=cfg.llm.model,
            model_prompt_name=cfg.prompt.active,
            model_request=request_metadata,
            model_attempts=model_attempts,
        )

    weather = normalize_weather(raw.get("w"))

    raw_track_value = str(raw.get("t") or "").strip()
    raw_track = fix_track_name(raw_track_value, refs)
    if not raw_track_value:
        track = "Unknown"
    elif raw_track is None:
        track = f"{_AMBIGUOUS_TRACK}: {raw_track_value}"
        log.warning(
            f"[pipeline] {filename}: track '{raw.get('t')}' matches multiple "
            f"layouts — flagging for review"
        )
    else:
        track = raw_track or "Unknown"

    temp_f = raw.get("tf")
    temp_c = fahrenheit_to_celsius(
        temp_f,
        cfg.validation.temp_min_f,
        cfg.validation.temp_max_f,
    )

    try:
        parsed_temp_f: float | None = (
            float(str(temp_f).replace(",", ".").strip()) if temp_f is not None else None
        )
    except (ValueError, TypeError):
        parsed_temp_f = None

    if temp_f is not None and temp_c is None:
        log.warning(f"[pipeline] {filename}: temperature {temp_f}F invalid or out of range — ignored")
    temp_f_val = parsed_temp_f if temp_c is not None else None

    entries: list[LapRecord] = []
    corrected_entries: list[dict] = []

    for raw_entry in raw.get("e", []):
        bl      = raw_entry.get("bl")
        best_lap_ms = parse_lap_time_ms(bl)
        if best_lap_ms is None:
            continue

        car_raw = str(raw_entry.get("ca", "")).strip()
        car     = fix_car_name(car_raw, refs)
        corrected_entries.append({"ca": car, "cl": raw_entry.get("cl", "")})

        driver = sanitize_driver_name(raw_entry.get("dr", ""))

        entries.append(LapRecord(
            driver       = driver,
            car          = car,
            car_class    = extract_class_letter(raw_entry.get("cl", "")),
            best_lap     = str(bl).strip(),
            best_lap_ms  = best_lap_ms,
            dirty        = is_dirty_lap(bl),
        ))

    if not entries:
        msg = "No valid lap times found after parsing"
        log.warning(f"[pipeline] {filename}: {msg}")
        return ExtractionResult(
            source_file=filename,
            file_hash=hash_value,
            session=None,
            status="error",
            error=msg,
            model_backend=LMSTUDIO_BACKEND_NAME,
            model_name=cfg.llm.model,
            model_prompt_name=cfg.prompt.active,
            model_request=request_metadata,
            model_response_stats=response_stats,
            model_attempts=model_attempts,
        )

    race_class = detect_race_class(corrected_entries)

    session = RaceSession(
        track      = track,
        temp_f     = temp_f_val,
        temp_c     = temp_c,
        entries    = entries,
        race_class = race_class,
        weather    = weather,
    )

    semantic_name = build_semantic_name(filename, track, race_class)
    raw_response_artifact_path = backend_raw_response_artifact_path

    log.debug(
        f"[pipeline] OK  {semantic_name}"
        f"  ({len(entries)} drivers, {race_class}, {weather})"
    )

    return ExtractionResult(
        source_file          = filename,
        file_hash            = hash_value,
        session              = session,
        status               = "ok",
        semantic_name        = semantic_name,
        current_path         = str(image_path),
        raw_response         = raw_response,
        raw_response_payload    = raw,
        raw_response_artifact_path    = raw_response_artifact_path,
        model_backend        = LMSTUDIO_BACKEND_NAME,
        model_name           = cfg.llm.model,
        model_prompt_name    = cfg.prompt.active,
        model_request        = request_metadata,
        model_response_stats = response_stats,
        model_attempts       = model_attempts,
    )

