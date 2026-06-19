from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class LMStudioLoadedInstance:
    id: str
    config: dict[str, Any]
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class LMStudioModel:
    id: str
    path: str = ""
    display_name: str = ""
    publisher: str = ""
    architecture: str = ""
    format: str = ""
    params_string: str = ""
    size_bytes: int | None = None
    max_context_length: int | None = None
    quantization: str = ""
    selected_variant: str = ""
    capabilities: dict[str, Any] | None = None
    loaded_instances: tuple[LMStudioLoadedInstance, ...] = ()
    raw: dict[str, Any] | None = None

    @property
    def label(self) -> str:
        return self.display_name or self.id or self.path


@dataclass(frozen=True)
class LMStudioRuntimeDiagnostic:
    level: str
    ok: bool
    message: str
    endpoint: str
    configured_model: str
    model_found: bool = False
    model_label: str = ""
    loaded: bool = False
    loaded_instances: int = 0
    instance_id: str = ""
    desired_config: dict[str, Any] | None = None
    effective_config: dict[str, Any] | None = None
    runtime_config_summary: str = ""
    capabilities_summary: str = ""
    model_info_summary: str = ""
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


class LMStudioRuntimeClient:
    """Small client for LM Studio runtime metadata used by GUI lab tools."""

    def __init__(self, url: str, *, timeout: int = 5, session: requests.Session | None = None) -> None:
        self.url = url
        self.timeout = timeout
        self._session = session or requests.Session()
        self._owns_session = session is None

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def list_models(self) -> list[LMStudioModel]:
        data = self._get_json("/models")
        rows = _model_rows(data)
        output: list[LMStudioModel] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            model_id = str(
                row.get("key") or row.get("id") or row.get("model_key") or row.get("path") or ""
            ).strip()
            if not model_id:
                continue
            quantization = row.get("quantization") if isinstance(row.get("quantization"), dict) else {}
            output.append(LMStudioModel(
                id=model_id,
                path=str(row.get("path") or ""),
                display_name=str(row.get("display_name") or row.get("name") or ""),
                publisher=str(row.get("publisher") or ""),
                architecture=str(row.get("architecture") or ""),
                format=str(row.get("format") or ""),
                params_string=str(row.get("params_string") or row.get("params") or ""),
                size_bytes=_int_or_none(row.get("size_bytes")),
                max_context_length=_int_or_none(row.get("max_context_length")),
                quantization=str(quantization.get("name") or ""),
                selected_variant=str(row.get("selected_variant") or ""),
                capabilities=row.get("capabilities") if isinstance(row.get("capabilities"), dict) else {},
                loaded_instances=_loaded_instances(row.get("loaded_instances")),
                raw=row,
            ))
        return output

    def list_model_keys(self) -> tuple[str, ...]:
        return tuple(model.id for model in self.list_models())

    def runtime_status(
        self,
        *,
        configured_model: str,
        desired_load_config: dict[str, Any] | None = None,
        reasoning_mode: str | None = None,
    ) -> LMStudioRuntimeDiagnostic:
        endpoint = _lmstudio_api_url(self.url, "/models")
        desired = _normalized_load_config(desired_load_config or {})
        try:
            models = self.list_models()
        except Exception as exc:
            return LMStudioRuntimeDiagnostic(
                level="error",
                ok=False,
                message=str(exc),
                endpoint=endpoint,
                configured_model=configured_model,
                desired_config=desired,
                errors=(str(exc),),
            )

        model = _find_model(models, configured_model)
        if model is None:
            message = f"Configured model not found ({configured_model})"
            return LMStudioRuntimeDiagnostic(
                level="error",
                ok=False,
                message=message,
                endpoint=endpoint,
                configured_model=configured_model,
                desired_config=desired,
                errors=(message,),
            )

        warnings: list[str] = []
        errors: list[str] = []
        loaded = bool(model.loaded_instances)
        effective = _normalized_load_config(model.loaded_instances[0].config) if loaded else {}
        instance_id = model.loaded_instances[0].id if loaded else ""
        if not loaded:
            warnings.append("Model is available but not loaded")
        elif len(model.loaded_instances) > 1:
            warnings.append(f"Multiple loaded instances ({len(model.loaded_instances)})")

        for key, desired_value in desired.items():
            if desired_value is None:
                continue
            effective_value = effective.get(key)
            if effective_value != desired_value:
                warnings.append(
                    f"Loaded {key} mismatch: configured {desired_value}, loaded {_display_config_value(effective_value)}"
                )

        vision = _capability_value(model.capabilities or {}, "vision")
        if vision is False:
            warnings.append("Model does not advertise vision capability")

        if model.max_context_length is not None:
            desired_context = _int_or_none(desired.get("context_length"))
            if desired_context is not None and desired_context > model.max_context_length:
                warnings.append(
                    f"context_length {desired_context} exceeds max_context_length {model.max_context_length}"
                )

        if reasoning_mode:
            reasoning_options = _reasoning_options(model.capabilities or {})
            if reasoning_options and reasoning_mode not in reasoning_options:
                warnings.append(
                    f"Reasoning mode mismatch: configured {reasoning_mode}, model allows {', '.join(reasoning_options)}"
                )

        level = "warning" if warnings else "ok"
        message = _runtime_message(model, loaded=loaded, warnings=warnings)
        return LMStudioRuntimeDiagnostic(
            level=level,
            ok=level == "ok",
            message=message,
            endpoint=endpoint,
            configured_model=configured_model,
            model_found=True,
            model_label=model.label,
            loaded=loaded,
            loaded_instances=len(model.loaded_instances),
            instance_id=instance_id,
            desired_config=desired,
            effective_config=effective,
            runtime_config_summary=_runtime_config_summary(desired, effective),
            capabilities_summary=_capabilities_summary(model.capabilities or {}, reasoning_mode),
            model_info_summary=_model_info_summary(model),
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    def health(self) -> tuple[bool, str]:
        try:
            models = self.list_models()
        except Exception as exc:
            return False, str(exc)
        return True, f"{len(models)} model(s) available"

    def _get_json(self, suffix: str) -> Any:
        response = self._session.get(
            _lmstudio_api_url(self.url, suffix),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


def _lmstudio_api_url(url: str, suffix: str) -> str:
    clean = url.rstrip("/")
    if "/api/v1/" in clean:
        base = clean.split("/api/v1/", 1)[0] + "/api/v1"
    elif clean.endswith("/api/v1"):
        base = clean
    elif "/v1/" in clean:
        base = clean.split("/v1/", 1)[0] + "/api/v1"
    else:
        base = clean
    return base.rstrip("/") + "/" + suffix.lstrip("/")


def _model_rows(data: Any) -> list[Any]:
    if isinstance(data, dict):
        rows = data.get("models")
        if isinstance(rows, list):
            return rows
        rows = data.get("data")
        if isinstance(rows, list):
            return rows
    return data if isinstance(data, list) else []


def _loaded_instances(raw: Any) -> tuple[LMStudioLoadedInstance, ...]:
    if not isinstance(raw, list):
        return ()
    instances: list[LMStudioLoadedInstance] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        instance_id = str(row.get("id") or row.get("instance_id") or "").strip()
        config = row.get("config") or row.get("load_config") or {}
        instances.append(LMStudioLoadedInstance(
            id=instance_id,
            config=config if isinstance(config, dict) else {},
            raw=row,
        ))
    return tuple(instances)


def _find_model(models: list[LMStudioModel], configured_model: str) -> LMStudioModel | None:
    configured = configured_model.strip()
    for model in models:
        raw = model.raw or {}
        candidates = {
            model.id,
            model.path,
            model.display_name,
            str(raw.get("key") or ""),
            str(raw.get("model_key") or ""),
        }
        if configured in candidates:
            return model
    return None


def _runtime_message(model: LMStudioModel, *, loaded: bool, warnings: list[str]) -> str:
    state = "loaded" if loaded else "available, not loaded"
    if warnings:
        return f"{model.label} · {state} · {len(warnings)} warning(s)"
    return f"{model.label} · loaded and compatible"


def _runtime_config_summary(desired: dict[str, Any], effective: dict[str, Any]) -> str:
    parts = []
    for label, key in (
        ("ctx", "context_length"),
        ("eval", "eval_batch_size"),
        ("phys", "physical_batch_size"),
        ("flash", "flash_attention"),
        ("kv", "offload_kv_cache_to_gpu"),
        ("parallel", "parallel"),
        ("experts", "num_experts"),
    ):
        loaded = effective.get(key)
        wanted = desired.get(key)
        if loaded is None and wanted is None:
            continue
        if wanted is not None and loaded != wanted:
            parts.append(f"{label} {_display_config_value(loaded)} (want {wanted})")
        else:
            parts.append(f"{label} {loaded if loaded is not None else wanted}")
    return " · ".join(parts) if parts else "No loaded runtime config"


def _capabilities_summary(capabilities: dict[str, Any], reasoning_mode: str | None) -> str:
    vision = _capability_value(capabilities, "vision")
    tool_use = _capability_value(capabilities, "trained_for_tool_use")
    reasoning = capabilities.get("reasoning") if isinstance(capabilities.get("reasoning"), dict) else {}
    options = _reasoning_options(capabilities)
    default = reasoning.get("default")
    parts = [
        f"vision={_display_bool(vision)}",
        f"tool_use={_display_bool(tool_use)}",
    ]
    if options:
        parts.append(f"reasoning={reasoning_mode or '-'} allowed[{', '.join(options)}]")
    elif default is not None:
        parts.append(f"reasoning default={default}")
    return " · ".join(parts)


def _model_info_summary(model: LMStudioModel) -> str:
    parts = [
        model.publisher,
        model.architecture,
        model.format,
        model.params_string,
        model.quantization,
        _format_size(model.size_bytes),
        f"max ctx {model.max_context_length}" if model.max_context_length is not None else "",
        f"variant {model.selected_variant}" if model.selected_variant else "",
    ]
    return " · ".join(part for part in parts if part) or model.id


def _reasoning_options(capabilities: dict[str, Any]) -> tuple[str, ...]:
    reasoning = capabilities.get("reasoning") if isinstance(capabilities.get("reasoning"), dict) else {}
    raw_options = reasoning.get("allowed_options") or reasoning.get("allowed")
    if not isinstance(raw_options, list):
        return ()
    return tuple(str(option) for option in raw_options if option is not None)


def _capability_value(capabilities: dict[str, Any], key: str) -> bool | None:
    value = capabilities.get(key)
    return value if isinstance(value, bool) else None


def _display_bool(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def _display_config_value(value: Any) -> str:
    return "missing" if value is None else str(value)


def _format_size(value: int | None) -> str:
    if value is None:
        return ""
    gib = value / (1024 ** 3)
    return f"{gib:.1f} GiB"


def _normalized_load_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in ("context_length", "eval_batch_size", "physical_batch_size", "parallel", "num_experts"):
        value = _load_config_value(config, key)
        int_value = _int_or_none(value)
        if int_value is not None:
            normalized[key] = int_value
    for key in ("flash_attention", "offload_kv_cache_to_gpu"):
        value = _load_config_value(config, key)
        bool_value = _bool_or_none(value)
        if bool_value is not None:
            normalized[key] = bool_value
    return normalized


def _load_config_value(config: dict[str, Any], key: str) -> Any:
    aliases = {
        "context_length": ("context_length", "contextLength", "n_ctx", "nCtx"),
        "eval_batch_size": ("eval_batch_size", "evalBatchSize"),
        "physical_batch_size": ("physical_batch_size", "physicalBatchSize"),
        "parallel": ("parallel",),
        "num_experts": ("num_experts", "numExperts"),
        "flash_attention": ("flash_attention", "flashAttention"),
        "offload_kv_cache_to_gpu": (
            "offload_kv_cache_to_gpu",
            "offloadKVCacheToGpu",
            "offloadKvCacheToGpu",
        ),
    }
    for alias in aliases[key]:
        if alias in config:
            return config[alias]
    return None


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    if isinstance(value, int):
        return bool(value)
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
