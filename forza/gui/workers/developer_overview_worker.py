from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from ...lmstudio import LMStudioRuntimeClient
from ...application.gui_read_service import GuiReadService
from ...application.gui_overview_service import fast_db_report




@dataclass(frozen=True)
class DeveloperOverviewSnapshot:
    lmstudio_ok: bool
    lmstudio_level: str
    lmstudio_message: str
    lmstudio_endpoint: str
    lmstudio_model: str
    lmstudio_loaded_instance: str
    lmstudio_configured_load: str
    lmstudio_configured_request: str
    lmstudio_configured_image: str
    lmstudio_runtime_policy: str
    lmstudio_loaded_runtime: str
    lmstudio_capabilities: str
    lmstudio_model_info: str
    lmstudio_warnings: str
    database_file: str
    schema_state: str
    db_ok: bool
    db_error_count: int
    db_warning_count: int
    db_check_profile: str = "fast"
    images: int = 0
    available_images: int = 0
    review_open: int = 0


@dataclass(frozen=True)
class DeveloperOverviewWorkerResult:
    ok: bool
    snapshot: DeveloperOverviewSnapshot | None = None
    message: str = ""


class DeveloperOverviewWorker(QObject):
    finished = Signal(object)

    def __init__(self, *, cfg: Any) -> None:
        super().__init__()
        self._cfg = cfg

    @Slot()
    def run(self) -> None:
        try:
            snapshot = _build_snapshot(self._cfg)
            payload = DeveloperOverviewWorkerResult(ok=True, snapshot=snapshot)
        except Exception as exc:  # pragma: no cover - GUI boundary
            payload = DeveloperOverviewWorkerResult(ok=False, message=str(exc))
        self.finished.emit(payload)


def _build_snapshot(cfg: Any) -> DeveloperOverviewSnapshot:
    lmstudio = _lmstudio_status(cfg)
    report = fast_db_report(Path(cfg.database_file))

    reader = GuiReadService(cfg.database_file)
    try:
        dashboard = reader.dashboard_summary()
    finally:
        reader.close()


    return DeveloperOverviewSnapshot(
        lmstudio_ok=lmstudio.ok,
        lmstudio_level=lmstudio.level,
        lmstudio_message=lmstudio.message,
        lmstudio_endpoint=lmstudio.endpoint,
        lmstudio_model=_model_line(lmstudio),
        lmstudio_loaded_instance=_loaded_instance_line(lmstudio),
        lmstudio_configured_load=_configured_load_line(cfg.llm),
        lmstudio_configured_request=_configured_request_line(cfg),
        lmstudio_configured_image=_configured_image_line(cfg),
        lmstudio_runtime_policy=_runtime_policy_line(cfg),
        lmstudio_loaded_runtime=lmstudio.runtime_config_summary or "—",
        lmstudio_capabilities=lmstudio.capabilities_summary or "—",
        lmstudio_model_info=lmstudio.model_info_summary or "—",
        lmstudio_warnings="; ".join((*lmstudio.errors, *lmstudio.warnings)) or "None",
        database_file=str(cfg.database_file),
        schema_state=report.schema_state,
        db_ok=report.ok,
        db_error_count=report.errors,
        db_warning_count=report.warnings,
        db_check_profile="fast",
        images=dashboard.images,
        available_images=dashboard.available_images,
        review_open=dashboard.review_open,
    )



def _lmstudio_status(cfg: Any):
    timeout = float(getattr(cfg, "gui_overview_lmstudio_timeout_s", 1.0) or 1.0)
    client = LMStudioRuntimeClient(cfg.llm.url, timeout=timeout)
    try:
        return client.runtime_status(
            configured_model=cfg.llm.model,
            desired_load_config=_desired_load_config(cfg.llm),
            reasoning_mode=getattr(cfg.llm, "reasoning_mode", None),
        )
    finally:
        client.close()


def _desired_load_config(llm: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "context_length": getattr(llm, "context_length", None),
        "eval_batch_size": getattr(llm, "eval_batch_size", None),
        "flash_attention": getattr(llm, "flash_attention", None),
        "offload_kv_cache_to_gpu": getattr(llm, "offload_kv_cache_to_gpu", None),
    }
    physical_batch_size = getattr(llm, "physical_batch_size", None)
    if physical_batch_size is not None:
        config["physical_batch_size"] = physical_batch_size
    return {key: value for key, value in config.items() if value is not None}


def _model_line(lmstudio) -> str:
    if not lmstudio.model_found:
        return lmstudio.configured_model
    if lmstudio.model_label == lmstudio.configured_model:
        return lmstudio.configured_model
    return f"{lmstudio.configured_model} -> {lmstudio.model_label}"


def _loaded_instance_line(lmstudio) -> str:
    if not lmstudio.model_found:
        return "Model not found"
    if not lmstudio.loaded:
        return "Not loaded"
    suffix = f" ({lmstudio.loaded_instances} loaded)" if lmstudio.loaded_instances != 1 else ""
    return f"{lmstudio.instance_id or 'loaded'}{suffix}"


def _configured_load_line(llm: Any) -> str:
    parts = [
        f"ctx {_display_optional(getattr(llm, 'context_length', None))}",
        f"eval {_display_optional(getattr(llm, 'eval_batch_size', None))}",
        f"phys {_display_optional(getattr(llm, 'physical_batch_size', None))}",
        f"flash {getattr(llm, 'flash_attention', None)}",
        f"kv {getattr(llm, 'offload_kv_cache_to_gpu', None)}",
    ]
    return " · ".join(parts)


def _configured_request_line(cfg: Any) -> str:
    llm = cfg.llm
    parts = [
        f"prompt {getattr(cfg.prompt, 'active', '-')}",
        f"format {getattr(llm, 'image_format', '-')}",
        f"max tokens {getattr(llm, 'max_completion_tokens', '-')}",
        f"temperature {getattr(llm, 'temperature', '-')}",
        f"reasoning {_display_optional(getattr(llm, 'reasoning_mode', None))}",
    ]
    return " · ".join(parts)


def _configured_image_line(cfg: Any) -> str:
    image = cfg.image
    return (
        f"max width {getattr(image, 'max_width', '-')} · "
        f"quality {getattr(image, 'encode_quality', '-')} · "
        f"grayscale {getattr(image, 'grayscale', '-') }"
    )


def _runtime_policy_line(cfg: Any) -> str:
    llm = cfg.llm
    return (
        f"reload if TPS < {getattr(llm, 'performance_tps_floor', '-')} for "
        f"{getattr(llm, 'performance_reload_streak', '-')} image(s) after "
        f"{getattr(llm, 'performance_reload_elapsed_s', '-')}s"
    )


def _display_optional(value: object) -> str:
    return "auto" if value in (None, "") else str(value)
