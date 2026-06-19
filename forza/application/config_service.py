from __future__ import annotations

import configparser
import copy
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import AppConfig, load_config, validate_config
from ..exceptions import ConfigValidationError


@dataclass(frozen=True)
class ConfigSaveResult:
    ok: bool
    message: str
    backup_path: Path | None = None


class ConfigFileService:
    """Safe writer for forza_config.ini.

    The GUI passes string changes. This service applies them to a copied
    AppConfig, validates the result, writes a timestamped backup, then updates
    known INI sections atomically. It is intentionally separate from widgets/views.
    """

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)

    def validate_changes(self, changes: dict[str, str]) -> ConfigSaveResult:
        if not changes:
            return ConfigSaveResult(True, "Configuration is valid for execution.")
        try:
            self._candidate_config(changes)
        except (ConfigValidationError, ValueError) as exc:
            return ConfigSaveResult(False, str(exc))
        return ConfigSaveResult(True, "Configuration is valid for execution.")

    def save_changes(self, changes: dict[str, str]) -> ConfigSaveResult:
        if not changes:
            return ConfigSaveResult(False, "No changes to save.")
        try:
            candidate = self._candidate_config(changes)
        except (ConfigValidationError, ValueError) as exc:
            return ConfigSaveResult(False, str(exc))
        backup = self._backup()
        self._write(candidate)
        return ConfigSaveResult(True, f"Configuration saved. Backup: {backup}", backup)

    def _candidate_config(self, changes: dict[str, str]) -> AppConfig:
        base = load_config(self.config_path, strict=True)
        candidate = copy.deepcopy(base)
        self._apply(candidate, changes)
        validate_config(candidate)
        return candidate

    def _read_parser(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser()
        if self.config_path.exists():
            parser.read(self.config_path, encoding="utf-8")
        return parser

    def _apply(self, cfg: AppConfig, changes: dict[str, str]) -> None:
        for field, raw_value in changes.items():
            value = raw_value.strip()
            if field.startswith("paths."):
                self._apply_path(cfg, field.removeprefix("paths."), value)
            elif field.startswith("llm."):
                self._apply_llm(cfg, field.removeprefix("llm."), value)
            elif field.startswith("image."):
                self._apply_image(cfg, field.removeprefix("image."), value)
            elif field.startswith("validation."):
                self._apply_validation(cfg, field.removeprefix("validation."), value)
            elif field.startswith("pdf."):
                self._apply_pdf(cfg, field.removeprefix("pdf."), value)
            elif field == "prompt.active":
                cfg.prompt.active = value
            elif field == "user.gamertag":
                cfg.gamertag = value
            else:
                raise ValueError(f"Field is not editable: {field}")

    def _apply_path(self, cfg: AppConfig, key: str, value: str) -> None:
        editable_paths = {
            "input_dir",
            "pdf_file",
            "log_file",
            "database_file",
        }
        if key not in editable_paths:
            raise ValueError(f"Field is not editable: paths.{key}")
        path = Path(value) if value else None
        if path is None:
            raise ValueError(f"[paths] {key} cannot be empty")
        setattr(cfg, key, path)

    def _apply_llm(self, cfg: AppConfig, key: str, value: str) -> None:
        if key == "workers":
            cfg.workers = int(value)
            return
        if key in {"max_completion_tokens", "timeout_connect", "timeout_read", "max_retries", "performance_reload_streak"}:
            setattr(cfg.llm, key, int(value))
            return
        if key in {"eval_batch_size", "physical_batch_size"}:
            parsed = int(value) if value else 0
            setattr(cfg.llm, key, parsed or None)
            return
        if key == "context_length":
            parsed = int(value) if value else 0
            cfg.llm.context_length = parsed or None
            return
        if key == "temperature":
            cfg.llm.temperature = float(value)
            return
        if key in {"performance_tps_floor", "performance_reload_elapsed_s"}:
            setattr(cfg.llm, key, float(value))
            return
        if key in {"flash_attention", "offload_kv_cache_to_gpu"}:
            setattr(cfg.llm, key, _bool(value))
            return
        if key in {"url", "model", "image_format", "reasoning_mode"}:
            setattr(cfg.llm, key, (value or None) if key == "reasoning_mode" else value)
            return
        raise ValueError(f"Unknown LLM field: {key}")

    def _apply_image(self, cfg: AppConfig, key: str, value: str) -> None:
        if key in {"max_width", "encode_quality"}:
            setattr(cfg.image, key, int(value))
            return
        if key == "grayscale":
            cfg.image.grayscale = _bool(value)
            return
        raise ValueError(f"Unknown image field: {key}")

    def _apply_validation(self, cfg: AppConfig, key: str, value: str) -> None:
        if key in {"temp_min_f", "temp_max_f"}:
            setattr(cfg.validation, key, float(value))
            return
        raise ValueError(f"Unknown validation field: {key}")

    def _apply_pdf(self, cfg: AppConfig, key: str, value: str) -> None:
        if key == "dirty_lap_symbol":
            cfg.pdf.dirty_lap_symbol = value
            return
        if key == "show_dirty_lap_symbol":
            cfg.pdf.show_dirty_lap_symbol = _bool(value)
            return
        raise ValueError(f"Unknown PDF field: {key}")

    def _backup(self) -> Path | None:
        if not self.config_path.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_path = self.config_path.with_name(f"{self.config_path.name}.{stamp}.bak")
        shutil.copy2(self.config_path, backup_path)
        return backup_path

    def _write(self, cfg: AppConfig) -> None:
        parser = self._read_parser()
        _ensure(parser, "paths")
        parser["paths"].update({
            "input_dir": str(cfg.input_dir),
            "pdf_file": str(cfg.pdf_file),
            "log_file": str(cfg.log_file),
            "database_file": str(cfg.database_file),
        })
        legacy_tracks_key = "tracks_" + "file"
        legacy_cars_key = "cars_" + "file"
        parser["paths"].pop(legacy_tracks_key, None)
        parser["paths"].pop(legacy_cars_key, None)
        parser["paths"].pop("output_dir", None)
        parser["paths"].pop("benchmark_file", None)
        parser["paths"].pop("raw_" + "artifacts_dir", None)
        parser["paths"].pop("raw" + "_dir", None)
        parser["paths"].pop("calibration_samples_dir", None)
        legacy_external_key = "external_" + "records" + "_file"
        parser["paths"].pop(legacy_external_key, None)
        for obsolete_key in ("review_dir", "corrections_dir", "manual_overrides_file"):
            parser["paths"].pop(obsolete_key, None)
        _ensure(parser, "user")
        parser["user"]["gamertag"] = cfg.gamertag
        _ensure(parser, "llm")
        parser["llm"].update({"workers": str(cfg.workers)})
        for obsolete_key in ("backend", "max_workers", "worker_mode"):
            parser["llm"].pop(obsolete_key, None)
        _ensure(parser, "lmstudio")
        parser["lmstudio"].update({
            "url": cfg.llm.url,
            "model": cfg.llm.model,
            "max_completion_tokens": str(cfg.llm.max_completion_tokens),
            "temperature": str(cfg.llm.temperature),
            "timeout_connect": str(cfg.llm.timeout_connect),
            "timeout_read": str(cfg.llm.timeout_read),
            "max_retries": str(cfg.llm.max_retries),
            "image_format": cfg.llm.image_format,
            "context_length": "" if cfg.llm.context_length is None else str(cfg.llm.context_length),
            "reasoning_mode": cfg.llm.reasoning_mode or "",
            "eval_batch_size": "" if cfg.llm.eval_batch_size is None else str(cfg.llm.eval_batch_size),
            "physical_batch_size": "" if cfg.llm.physical_batch_size is None else str(cfg.llm.physical_batch_size),
            "flash_attention": str(cfg.llm.flash_attention),
            "offload_kv_cache_to_gpu": str(cfg.llm.offload_kv_cache_to_gpu),
            "performance_tps_floor": str(cfg.llm.performance_tps_floor),
            "performance_reload_elapsed_s": str(cfg.llm.performance_reload_elapsed_s),
            "performance_reload_streak": str(cfg.llm.performance_reload_streak),
        })
        parser["lmstudio"].pop("api_family", None)
        parser["lmstudio"].pop("max_parse_retries", None)
        if parser.has_section("ollama"):
            parser.remove_section("ollama")
        _ensure(parser, "image")
        parser["image"].update({
            "max_width": str(cfg.image.max_width),
            "encode_quality": str(cfg.image.encode_quality),
            "grayscale": str(cfg.image.grayscale),
        })
        _ensure(parser, "validation")
        parser["validation"].update({
            "temp_min_f": str(cfg.validation.temp_min_f),
            "temp_max_f": str(cfg.validation.temp_max_f),
        })
        _ensure(parser, "pdf")
        parser["pdf"].update({
            "dirty_lap_symbol": cfg.pdf.dirty_lap_symbol,
            "show_dirty_lap_symbol": str(cfg.pdf.show_dirty_lap_symbol),
        })
        _ensure(parser, "prompt")
        parser["prompt"]["active"] = cfg.prompt.active
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.config_path.with_name(f"{self.config_path.name}.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            parser.write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(self.config_path)



def _ensure(parser: configparser.ConfigParser, section: str) -> None:
    if not parser.has_section(section):
        parser.add_section(section)



def _bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")
