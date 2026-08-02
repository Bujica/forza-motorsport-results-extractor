from __future__ import annotations

from forza.lmstudio.load_config import (
    desired_load_config,
    instance_load_config,
    load_config_compatible,
    normalized_load_config,
)


def test_desired_load_config_omits_none_optional_batch_size() -> None:
    assert desired_load_config(
        context_length=8192,
        eval_batch_size=None,
        physical_batch_size=None,
        flash_attention=True,
        offload_kv_cache_to_gpu=False,
    ) == {
        "context_length": 8192,
        "flash_attention": True,
        "offload_kv_cache_to_gpu": False,
    }


def test_normalized_load_config_accepts_lmstudio_aliases() -> None:
    assert normalized_load_config({
        "contextLength": "8192",
        "evalBatchSize": "1024",
        "physicalBatchSize": 256,
        "flashAttention": "true",
        "offloadKVCacheToGpu": 0,
    }) == {
        "context_length": 8192,
        "eval_batch_size": 1024,
        "physical_batch_size": 256,
        "flash_attention": True,
        "offload_kv_cache_to_gpu": False,
    }


def test_instance_load_config_prefers_config_then_load_config_dicts() -> None:
    assert instance_load_config({"config": {"context_length": 4096}}) == {"context_length": 4096}
    assert instance_load_config({"load_config": {"context_length": 2048}}) == {"context_length": 2048}
    assert instance_load_config({"config": "not-a-dict"}) == {}


def test_load_config_compatible_compares_normalized_values() -> None:
    desired = {
        "context_length": 8192,
        "eval_batch_size": 1024,
        "flash_attention": True,
    }

    assert load_config_compatible({
        "contextLength": "8192",
        "evalBatchSize": "1024",
        "flashAttention": "true",
    }, desired)
    assert not load_config_compatible({
        "contextLength": "4096",
        "evalBatchSize": "1024",
        "flashAttention": "true",
    }, desired)


def test_load_config_compatible_ignores_physical_batch_size_the_server_never_echoes_back() -> None:
    """Regression: physical_batch_size is a valid /models/load request field,
    but LM Studio's GET /api/v1/models never reports it back in
    loaded_instances[].config (confirmed against the documented response
    schema — only context_length, eval_batch_size, parallel, flash_attention,
    num_experts, offload_kv_cache_to_gpu are present). Comparing it caused a
    real production bug: the model reloaded on every single extraction call
    even though it was already loaded with the exact requested settings.
    """
    desired = {
        "context_length": 5120,
        "eval_batch_size": 1024,
        "physical_batch_size": 512,
        "flash_attention": True,
        "offload_kv_cache_to_gpu": True,
    }
    # Shape of a real GET /api/v1/models loaded_instances[].config response —
    # no physical_batch_size key at all, exactly as LM Studio documents it.
    real_server_reported_config = {
        "context_length": 5120,
        "eval_batch_size": 1024,
        "parallel": 1,
        "flash_attention": True,
        "offload_kv_cache_to_gpu": True,
    }

    assert load_config_compatible(real_server_reported_config, desired)


def test_load_config_compatible_treats_rounded_up_context_length_as_compatible() -> None:
    """Regression: LM Studio/llama.cpp can round the effective context length
    up to an internal alignment boundary rather than honoring the exact
    requested value — observed in production: requesting 5000 loads as 5120.
    A larger-than-requested context is still fully usable and must not force
    a reload; a *smaller* effective context must still be treated as
    incompatible.
    """
    desired = {"context_length": 5000, "flash_attention": True}

    assert load_config_compatible({"context_length": 5120, "flash_attention": True}, desired)
    assert load_config_compatible({"context_length": 5000, "flash_attention": True}, desired)
    assert not load_config_compatible({"context_length": 4096, "flash_attention": True}, desired)
