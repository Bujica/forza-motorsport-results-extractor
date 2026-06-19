from __future__ import annotations

from dataclasses import make_dataclass, replace
from pathlib import Path

import pytest

from forza.config import AppConfig, ImageConfig, LLMConfig, PDFConfig, PromptConfig, ValidationConfig
from forza.gui.config_state import ConfigChangeSet, _iter_config_values


EXPECTED_CONFIG_DIFF_KEYS = {
    "paths.input_dir",
    "paths.pdf_file",
    "paths.log_file",
    "paths.database_file",
    "user.gamertag",
    "llm.workers",
    "llm.url",
    "llm.model",
    "llm.max_completion_tokens",
    "llm.temperature",
    "llm.timeout_connect",
    "llm.timeout_read",
    "llm.max_retries",
    "llm.image_format",
    "llm.context_length",
    "llm.reasoning_mode",
    "llm.eval_batch_size",
    "llm.physical_batch_size",
    "llm.flash_attention",
    "llm.offload_kv_cache_to_gpu",
    "llm.performance_tps_floor",
    "llm.performance_reload_elapsed_s",
    "llm.performance_reload_streak",
    "image.max_width",
    "image.encode_quality",
    "image.grayscale",
    "validation.temp_min_f",
    "validation.temp_max_f",
    "pdf.dirty_lap_symbol",
    "pdf.show_dirty_lap_symbol",
    "prompt.active",
}


def _sample_config() -> AppConfig:
    return AppConfig(
        input_dir=Path("data/input"),
        pdf_file=Path("output/reports/forza_bestlaps.pdf"),
        log_file=Path("output/logs/forza_debug.log"),
        database_file=Path("data/forza.sqlite3"),
        gamertag="Player",
        workers=1,
        llm=LLMConfig(
            url="http://127.0.0.1:1234/v1/chat/completions",
            model="model-a",
            max_completion_tokens=1000,
            temperature=0.0,
            timeout_connect=10,
            timeout_read=180,
            max_retries=3,
            image_format="png",
        ),
        image=ImageConfig(max_width=2560, encode_quality=85, grayscale=True),
        validation=ValidationConfig(temp_min_f=40.0, temp_max_f=140.0),
        pdf=PDFConfig(dirty_lap_symbol="†", show_dirty_lap_symbol=True),
        prompt=PromptConfig(active="default"),
    )


def test_iter_config_values_covers_public_gui_diff_key_set() -> None:
    keys = {key for key, _value in _iter_config_values(_sample_config())}

    assert keys == EXPECTED_CONFIG_DIFF_KEYS


def test_config_change_set_detects_top_level_nested_and_path_changes() -> None:
    old = _sample_config()
    new = replace(
        old,
        input_dir=Path("new/input"),
        workers=3,
        llm=replace(old.llm, temperature=0.25),
        image=replace(old.image, grayscale=False),
        pdf=replace(old.pdf, show_dirty_lap_symbol=False),
    )

    changes = ConfigChangeSet.from_configs(old, new)

    assert changes.changed == frozenset(
        {
            "paths.input_dir",
            "llm.workers",
            "llm.temperature",
            "image.grayscale",
            "pdf.show_dirty_lap_symbol",
        }
    )
    assert changes.affects("paths")
    assert changes.affects("llm")
    assert changes.affects("image.grayscale")
    assert changes.affects("pdf")
    assert not changes.affects("paths.database_file")


def test_new_top_level_app_config_field_requires_explicit_diff_key_mapping() -> None:
    ExtendedConfig = make_dataclass(
        "ExtendedConfig",
        [(field.name, field.type) for field in AppConfig.__dataclass_fields__.values()] + [("new_field", str)],
    )
    base = _sample_config()
    extended = ExtendedConfig(**base.__dict__, new_field="value")

    with pytest.raises(ValueError, match="new_field"):
        list(_iter_config_values(extended))
