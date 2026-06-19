from __future__ import annotations

import configparser
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .domain.race_class import CLASS_ORDER
from .exceptions import ConfigValidationError
from .prompts import DEFAULT_PROMPT_ID, SYSTEM_PROMPTS

_log = logging.getLogger("forza")

CLASS_COLORS: dict[str, str] = {
    "E": "#C7368E", "D": "#127F85", "C": "#BB7A00",
    "B": "#C54E00", "A": "#992800", "TCR": "#1E90FF",
    "S": "#613BBF", "R": "#105DAB", "P": "#0C8540",
    "X": "#006000", "Mixed": "#555555", "Unknown": "#000000",
}


@dataclass
class LLMConfig:
    url: str
    model: str
    max_completion_tokens: int
    temperature: float
    timeout_connect: int
    timeout_read: int
    max_retries: int
    image_format: Literal["jpeg", "png", "webp"]
    context_length: int | None = None
    reasoning_mode: str | None = None
    eval_batch_size: int | None = None
    physical_batch_size: int | None = None
    flash_attention: bool = True
    offload_kv_cache_to_gpu: bool = True
    performance_tps_floor: float = 20.0
    performance_reload_elapsed_s: float = 45.0
    performance_reload_streak: int = 3


@dataclass
class ImageConfig:
    max_width: int
    encode_quality: int
    grayscale: bool


@dataclass
class ValidationConfig:
    temp_min_f: float
    temp_max_f: float


@dataclass
class PDFConfig:
    dirty_lap_symbol: str
    show_dirty_lap_symbol: bool


@dataclass
class PromptConfig:
    active: str


@dataclass
class AppConfig:
    input_dir:             Path
    pdf_file:              Path
    log_file:              Path
    database_file:         Path
    gamertag:              str
    workers:               int
    llm:                   LLMConfig
    image:                 ImageConfig
    validation:            ValidationConfig
    pdf:                   PDFConfig
    prompt:                PromptConfig


LMSTUDIO_DEFAULTS: dict[str, object] = {
    "url":             "http://127.0.0.1:1234/api/v1/chat",
    "model":           "qwen/qwen3.5-9b",
    "timeout_connect": 10,
    "timeout_read":    180,
    "image_format":    "png",
    "context_length":  5000,
    "reasoning_mode":  "off",
    "eval_batch_size": 1024,
}

_VALID_IMAGE_FORMATS = {"jpeg", "png", "webp"}
_VALID_REASONING_MODES = {"off", "on", "auto", "low", "medium", "high"}


def _get(
    cfg: configparser.ConfigParser,
    section: str,
    key: str,
    fallback,
    cast=None,
    *,
    strict: bool = False,
):
    try:
        if cast is bool:
            return cfg.getboolean(section, key, fallback=fallback)
        val = cfg.get(section, key, fallback=None)
        if val is None:
            return fallback
        return cast(val) if cast else val
    except Exception as exc:
        if strict:
            raise ConfigValidationError(
                f"Invalid config value [{section}] {key}: {exc}"
            ) from exc
        _log.warning(
            "Invalid config value [%s] %s; using fallback %r (%s)",
            section,
            key,
            fallback,
            exc,
        )
        return fallback


def _optional_int(
    cfg: configparser.ConfigParser,
    section: str,
    key: str,
    fallback: int | None,
    *,
    strict: bool = False,
) -> int | None:
    raw = _get(cfg, section, key, fallback, strict=strict)
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except Exception as exc:
        if strict:
            raise ConfigValidationError(
                f"Invalid config value [{section}] {key}: {exc}"
            ) from exc
        _log.warning(
            "Invalid config value [%s] %s; using fallback %r (%s)",
            section,
            key,
            fallback,
            exc,
        )
        return fallback


def load_config(path: str | Path = "forza_config.ini", *, strict: bool = False) -> AppConfig:
    cfg = configparser.ConfigParser()
    cfg.read(str(path), encoding="utf-8")

    d = LMSTUDIO_DEFAULTS

    llm = LLMConfig(
        url=_get(cfg, "lmstudio", "url", d["url"], strict=strict),
        model=_get(cfg, "lmstudio", "model", d["model"], strict=strict),
        max_completion_tokens=_get(cfg, "lmstudio", "max_completion_tokens", 1000, int, strict=strict),
        temperature=_get(cfg, "lmstudio", "temperature", 0.0, float, strict=strict),
        timeout_connect=_get(cfg, "lmstudio", "timeout_connect", d["timeout_connect"], int, strict=strict),
        timeout_read=_get(cfg, "lmstudio", "timeout_read", d["timeout_read"], int, strict=strict),
        max_retries=_get(cfg, "lmstudio", "max_retries", 3, int, strict=strict),
        image_format=_get(cfg, "lmstudio", "image_format", d["image_format"], strict=strict),
        context_length=_optional_int(cfg, "lmstudio", "context_length", d.get("context_length"), strict=strict),
        reasoning_mode=_get(cfg, "lmstudio", "reasoning_mode", d.get("reasoning_mode"), strict=strict) or None,
        eval_batch_size=_optional_int(cfg, "lmstudio", "eval_batch_size", d.get("eval_batch_size"), strict=strict),
        physical_batch_size=_optional_int(cfg, "lmstudio", "physical_batch_size", None, strict=strict),
        flash_attention=_get(cfg, "lmstudio", "flash_attention", True, bool, strict=strict),
        offload_kv_cache_to_gpu=_get(cfg, "lmstudio", "offload_kv_cache_to_gpu", True, bool, strict=strict),
        performance_tps_floor=_get(cfg, "lmstudio", "performance_tps_floor", 20.0, float, strict=strict),
        performance_reload_elapsed_s=_get(cfg, "lmstudio", "performance_reload_elapsed_s", 45.0, float, strict=strict),
        performance_reload_streak=_get(cfg, "lmstudio", "performance_reload_streak", 3, int, strict=strict),
    )

    image = ImageConfig(
        max_width=_get(cfg, "image", "max_width", 2560, int, strict=strict),
        encode_quality=_get(cfg, "image", "encode_quality", 85, int, strict=strict),
        grayscale=_get(cfg, "image", "grayscale", True, bool, strict=strict),
    )

    validation = ValidationConfig(
        temp_min_f=_get(cfg, "validation", "temp_min_f", 40.0, float, strict=strict),
        temp_max_f=_get(cfg, "validation", "temp_max_f", 140.0, float, strict=strict),
    )

    pdf = PDFConfig(
        dirty_lap_symbol=_get(cfg, "pdf", "dirty_lap_symbol", "†", strict=strict),
        show_dirty_lap_symbol=_get(cfg, "pdf", "show_dirty_lap_symbol", True, bool, strict=strict),
    )

    prompt = PromptConfig(
        active=_get(cfg, "prompt", "active", DEFAULT_PROMPT_ID, strict=strict),
    )


    return AppConfig(
        input_dir=Path(_get(cfg, "paths", "input_dir", "data/input", strict=strict)),
        pdf_file=Path(_get(cfg, "paths", "pdf_file", "output/reports/forza_bestlaps.pdf", strict=strict)),
        log_file=Path(_get(cfg, "paths", "log_file", "output/logs/forza_debug.log", strict=strict)),
        database_file=Path(_get(cfg, "paths", "database_file", "data/forza.sqlite3", strict=strict)),
        gamertag=_get(cfg, "user", "gamertag", "Player", strict=strict),
        workers=_get(cfg, "llm", "workers", 1, int, strict=strict),
        llm=llm,
        image=image,
        validation=validation,
        pdf=pdf,
        prompt=prompt,
    )


def validate_config(cfg: AppConfig) -> None:
    """Validate an AppConfig. Raises ConfigValidationError listing all failures."""
    errors: list[str] = []

    if cfg.llm.image_format not in _VALID_IMAGE_FORMATS:
        errors.append(
            f"[lmstudio] image_format={cfg.llm.image_format!r} is not valid. "
            f"Must be one of: {sorted(_VALID_IMAGE_FORMATS)}"
        )
    if cfg.llm.reasoning_mode is not None and cfg.llm.reasoning_mode not in _VALID_REASONING_MODES:
        errors.append(
            f"[lmstudio] reasoning_mode={cfg.llm.reasoning_mode!r} is not valid. "
            f"Must be one of: {sorted(_VALID_REASONING_MODES)}"
        )
    if cfg.prompt.active not in SYSTEM_PROMPTS:
        errors.append(
            f"[prompt] active={cfg.prompt.active!r} is not a registered prompt. "
            f"Available: {sorted(SYSTEM_PROMPTS)}"
        )
    if cfg.workers < 1:
        errors.append(f"[llm] workers={cfg.workers} must be >= 1")
    if cfg.llm.timeout_read <= 0:
        errors.append(f"[lmstudio] timeout_read={cfg.llm.timeout_read} must be > 0")
    if cfg.llm.timeout_connect <= 0:
        errors.append(f"[lmstudio] timeout_connect={cfg.llm.timeout_connect} must be > 0")
    if cfg.llm.context_length is not None and cfg.llm.context_length <= 0:
        errors.append(f"[lmstudio] context_length={cfg.llm.context_length} must be > 0")
    if cfg.llm.eval_batch_size is not None and cfg.llm.eval_batch_size <= 0:
        errors.append(f"[lmstudio] eval_batch_size={cfg.llm.eval_batch_size} must be > 0")
    if cfg.llm.physical_batch_size is not None and cfg.llm.physical_batch_size <= 0:
        errors.append(f"[lmstudio] physical_batch_size={cfg.llm.physical_batch_size} must be > 0")
    if cfg.llm.performance_reload_streak < 1:
        errors.append(f"[lmstudio] performance_reload_streak={cfg.llm.performance_reload_streak} must be >= 1")
    if cfg.image.max_width < 640 or cfg.image.max_width > 4096:
        errors.append(f"[image] max_width={cfg.image.max_width} is out of range [640, 4096]")
    if cfg.image.encode_quality < 1 or cfg.image.encode_quality > 100:
        errors.append(f"[image] encode_quality={cfg.image.encode_quality} is out of range [1, 100]")
    if cfg.validation.temp_min_f >= cfg.validation.temp_max_f:
        errors.append(
            f"[validation] temp_min_f ({cfg.validation.temp_min_f}) must be "
            f"less than temp_max_f ({cfg.validation.temp_max_f})"
        )
    for label, path, is_directory in _writable_path_checks(cfg):
        candidate = path if is_directory and path.exists() else path.parent
        parent = _nearest_existing_parent(candidate)
        if parent is not None and not os.access(parent, os.W_OK):
            errors.append(f"[paths] {label} parent is not writable: {parent}")

    if errors:
        bullet = "\n  • "
        msg = "Configuration errors:" + bullet + bullet.join(errors)
        raise ConfigValidationError(msg)


def _writable_path_checks(cfg: AppConfig) -> list[tuple[str, Path, bool]]:
    paths: list[tuple[str, Path, bool]] = [
        ("input_dir", cfg.input_dir, True),
        ("pdf_file", cfg.pdf_file, False),
        ("log_file", cfg.log_file, False),
        ("database_file", cfg.database_file, False),
    ]
    return paths


def _nearest_existing_parent(path: Path) -> Path | None:
    current = path
    while not current.exists():
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return current
