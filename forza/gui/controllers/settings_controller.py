from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ...config import AppConfig, validate_config
from ...exceptions import ConfigValidationError
from ..config_state import ConfigChangeSet, GuiConfigState


@dataclass(frozen=True)
class SettingsRow:
    key: str
    name: str
    value: str
    status: str = "ok"
    editable: bool = False
    editor: str = "text"
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class SettingsSnapshot:
    paths: list[SettingsRow]
    llm: list[SettingsRow]
    runtime: list[SettingsRow]
    validation_ok: bool
    validation_message: str
    dirty: bool = False


class SettingsController(QObject):
    settings_changed = Signal(object)
    action_completed = Signal(str)
    action_failed = Signal(str)

    def __init__(
        self,
        *,
        config_state: GuiConfigState,
        debug: bool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_state = config_state
        self._cfg = config_state.current
        self._debug = debug
        self._pending_changes: dict[str, str] = {}

    def refresh(self) -> None:
        self._cfg = self._config_state.reload(strict=False, emit=False)
        self._pending_changes = {}
        self.settings_changed.emit(self._snapshot())

    def preview_changes(self, changes: dict[str, str]) -> None:
        self._pending_changes = dict(changes)
        validation = self._config_state.validate_changes(self._pending_changes)
        self.settings_changed.emit(
            self._snapshot(
                dirty=bool(self._pending_changes),
                validation_override=(validation.ok, validation.message),
            )
        )

    def save_changes(self, changes: dict[str, str]) -> None:
        result = self._config_state.save_changes(changes)
        if result.ok:
            self._cfg = self._config_state.current
            self._pending_changes = {}
            self.action_completed.emit(result.message)
            self.settings_changed.emit(self._snapshot())
        else:
            self.action_failed.emit(result.message)
            self.settings_changed.emit(self._snapshot(dirty=bool(changes), validation_override=(False, result.message)))

    def on_config_changed(self, cfg: AppConfig, _changes: ConfigChangeSet) -> None:
        self._cfg = cfg
        self._pending_changes = {}
        self.settings_changed.emit(self._snapshot())

    def _snapshot(self, *, dirty: bool = False, validation_override: tuple[bool, str] | None = None) -> SettingsSnapshot:
        ok, message = validation_override or self._validate()
        return SettingsSnapshot(
            paths=self._apply_pending(self._paths()),
            llm=self._apply_pending(self._llm()),
            runtime=self._apply_pending(self._runtime()),
            validation_ok=ok,
            validation_message=message,
            dirty=dirty,
        )

    def _paths(self) -> list[SettingsRow]:
        cfg = self._cfg
        rows = [
            _editable_path("paths.input_dir", "input_dir", cfg.input_dir, _dir_status(cfg.input_dir)),
            _editable_path("paths.pdf_file", "pdf_file", cfg.pdf_file, _parent_status(cfg.pdf_file)),
            _editable_path("paths.log_file", "log_file", cfg.log_file, _parent_status(cfg.log_file)),
        ]
        return rows

    def _llm(self) -> list[SettingsRow]:
        llm = self._cfg.llm
        return [
            SettingsRow("llm.url", "url", llm.url, editable=True),
            SettingsRow("llm.model", "model", llm.model, editable=True),
            SettingsRow("prompt.active", "prompt.active", self._cfg.prompt.active, editable=True, editor="choice", options=_prompt_options()),
            SettingsRow("llm.max_completion_tokens", "max_completion_tokens", str(llm.max_completion_tokens), editable=True, editor="int", options=("64", "8192", "64")),
            SettingsRow("llm.temperature", "temperature", str(llm.temperature), editable=True, editor="float", options=("0", "2", "0.05")),
            SettingsRow("llm.timeout_connect", "timeout_connect", str(llm.timeout_connect), editable=True, editor="int", options=("1", "120", "1")),
            SettingsRow("llm.timeout_read", "timeout_read", str(llm.timeout_read), editable=True, editor="int", options=("10", "900", "10")),
            SettingsRow("llm.max_retries", "max_retries", str(llm.max_retries), editable=True, editor="int", options=("0", "10", "1")),
            SettingsRow("llm.image_format", "image_format", llm.image_format, editable=True, editor="choice", options=("png", "jpeg", "webp")),
            SettingsRow("llm.context_length", "context_length", "" if llm.context_length is None else str(llm.context_length), editable=True, editor="int", options=("0", "32768", "256")),
            SettingsRow("llm.reasoning_mode", "reasoning_mode", llm.reasoning_mode or "", editable=True, editor="choice", options=("off", "on", "auto", "low", "medium", "high")),
            SettingsRow("llm.eval_batch_size", "eval_batch_size", "" if llm.eval_batch_size is None else str(llm.eval_batch_size), editable=True, editor="int", options=("0", "4096", "64")),
            SettingsRow("llm.physical_batch_size", "physical_batch_size", "" if llm.physical_batch_size is None else str(llm.physical_batch_size), editable=True, editor="int", options=("0", "4096", "64")),
            SettingsRow("llm.flash_attention", "flash_attention", str(llm.flash_attention), editable=True, editor="bool"),
            SettingsRow("llm.offload_kv_cache_to_gpu", "offload_kv_cache_to_gpu", str(llm.offload_kv_cache_to_gpu), editable=True, editor="bool"),
            SettingsRow("llm.performance_tps_floor", "performance_tps_floor", str(llm.performance_tps_floor), editable=True, editor="float", options=("0", "500", "1")),
            SettingsRow("llm.performance_reload_elapsed_s", "performance_reload_elapsed_s", str(llm.performance_reload_elapsed_s), editable=True, editor="float", options=("0", "900", "5")),
            SettingsRow("llm.performance_reload_streak", "performance_reload_streak", str(llm.performance_reload_streak), editable=True, editor="int", options=("1", "20", "1")),
        ]

    def _runtime(self) -> list[SettingsRow]:
        return [
            SettingsRow("user.gamertag", "gamertag", self._cfg.gamertag, editable=True),
            SettingsRow("llm.workers", "workers", str(self._cfg.workers), editable=True, editor="int", options=("1", "16", "1")),
            SettingsRow("image.max_width", "image.max_width", str(self._cfg.image.max_width), editable=True, editor="int", options=("640", "4096", "64")),
            SettingsRow("image.encode_quality", "image.encode_quality", str(self._cfg.image.encode_quality), editable=True, editor="int", options=("1", "100", "1")),
            SettingsRow("image.grayscale", "image.grayscale", str(self._cfg.image.grayscale), editable=True, editor="bool"),
            SettingsRow("validation.temp_min_f", "validation.temp_min_f", str(self._cfg.validation.temp_min_f), editable=True, editor="float", options=("-100", "250", "1")),
            SettingsRow("validation.temp_max_f", "validation.temp_max_f", str(self._cfg.validation.temp_max_f), editable=True, editor="float", options=("-100", "250", "1")),
            SettingsRow("pdf.dirty_lap_symbol", "pdf.dirty_lap_symbol", self._cfg.pdf.dirty_lap_symbol, editable=True),
            SettingsRow("pdf.show_dirty_lap_symbol", "pdf.show_dirty_lap_symbol", str(self._cfg.pdf.show_dirty_lap_symbol), editable=True, editor="bool"),
        ]

    def _apply_pending(self, rows: list[SettingsRow]) -> list[SettingsRow]:
        return [
            replace(row, value=self._pending_changes[row.key], status="pending")
            if row.key in self._pending_changes else row
            for row in rows
        ]

    def _validate(self) -> tuple[bool, str]:
        try:
            validate_config(self._cfg)
        except ConfigValidationError as exc:
            return False, str(exc)
        return True, "Configuration is valid for execution."


def _editable_path(key: str, name: str, path: Path, status: str) -> SettingsRow:
    return SettingsRow(key, name, str(path), status, True)


def _path(path: Path | None) -> str:
    return "" if path is None else str(path)


def _dir_status(path: Path) -> str:
    if path.exists() and path.is_dir():
        return "ok"
    if path.exists() and not path.is_dir():
        return "invalid"
    return "missing"


def _parent_status(path: Path) -> str:
    parent = path.parent
    if parent.exists() and parent.is_dir():
        return "ok"
    if parent.exists() and not parent.is_dir():
        return "invalid"
    return "missing"


def _prompt_options() -> tuple[str, ...]:
    from ...prompts import SYSTEM_PROMPTS

    return tuple(sorted(SYSTEM_PROMPTS))
