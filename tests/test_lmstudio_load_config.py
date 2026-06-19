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
