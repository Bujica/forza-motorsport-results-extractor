from __future__ import annotations

from typing import Any

# physical_batch_size is accepted by POST /models/load as a request
# parameter, but LM Studio's GET /api/v1/models response never echoes it
# back in loaded_instances[].config — the documented schema for a loaded
# instance's config only includes context_length, eval_batch_size, parallel,
# flash_attention, num_experts, and offload_kv_cache_to_gpu (see
# https://lmstudio.ai/docs/developer/rest/list). Comparing physical_batch_size
# against the server's reported config is therefore a comparison against a
# field that's structurally never present, producing a false "mismatch"
# every time — which forces a needless unload+reload on every extraction and
# a permanent false-positive warning in DB Doctor/Diagnostics, even when the
# model is genuinely already loaded with the requested settings.
UNCOMPARABLE_LOAD_CONFIG_KEYS: frozenset[str] = frozenset({"physical_batch_size"})


def desired_load_config(
    *,
    context_length: int,
    eval_batch_size: int | None,
    physical_batch_size: int | None,
    flash_attention: bool,
    offload_kv_cache_to_gpu: bool,
) -> dict[str, Any]:
    """Build the LM Studio load-config payload for the configured backend."""
    config: dict[str, Any] = {
        "context_length": context_length,
        "eval_batch_size": eval_batch_size,
        "flash_attention": flash_attention,
        "offload_kv_cache_to_gpu": offload_kv_cache_to_gpu,
    }
    if physical_batch_size is not None:
        config["physical_batch_size"] = physical_batch_size
    return {key: value for key, value in config.items() if value is not None}


def instance_load_config(instance: dict[str, Any]) -> dict[str, Any]:
    config = instance.get("config") or instance.get("load_config") or {}
    return config if isinstance(config, dict) else {}


def normalized_load_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in ("context_length", "eval_batch_size", "physical_batch_size"):
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


def load_config_value_satisfies(key: str, desired_value: Any, effective_value: Any) -> bool:
    """Return True if the currently-loaded value for `key` satisfies `desired_value`.

    Most fields require exact equality. `context_length` is the one
    exception: LM Studio / llama.cpp can round the effective context length
    up to an internal alignment boundary rather than honoring the exact
    requested value (observed in production: requesting 5000 loads as 5120).
    A loaded context at least as large as requested is fully usable — only a
    *smaller* effective context is a real incompatibility — so this is a
    "at least as much" check rather than exact equality.
    """
    if key == "context_length":
        return effective_value is not None and effective_value >= desired_value
    return effective_value == desired_value


def load_config_compatible(existing: dict[str, Any], desired: dict[str, Any]) -> bool:
    normalized_existing = normalized_load_config(existing)
    for key, value in desired.items():
        if value is None or key in UNCOMPARABLE_LOAD_CONFIG_KEYS:
            continue
        if not load_config_value_satisfies(key, value, normalized_existing.get(key)):
            return False
    return True


def _load_config_value(config: dict[str, Any], key: str) -> Any:
    aliases = {
        "context_length": ("context_length", "contextLength", "n_ctx", "nCtx"),
        "eval_batch_size": ("eval_batch_size", "evalBatchSize"),
        "physical_batch_size": ("physical_batch_size", "physicalBatchSize"),
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


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
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
