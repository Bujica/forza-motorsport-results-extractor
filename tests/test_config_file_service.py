from __future__ import annotations

import configparser

from forza.config import load_config
from forza.prompts import DEFAULT_PROMPT_ID
from forza.application.config_service import ConfigFileService



def _write_config(path) -> None:
    path.write_text(
        "\n".join(
            [
                "[paths]",
                "input_dir = data/input",
                "pdf_file = output/reports/forza_bestlaps.pdf",
                "log_file = output/logs/forza_debug.log",
                "benchmark_file = output/logs/benchmark_log.txt",
                "database_file = data/forza.sqlite3",
                "raw_" + "artifacts_dir = debug/" + "raw_" + "responses",
                "",
                "[user]",
                "gamertag = Bujica89",
                "",
                "[llm]",
                "max_workers = 2",
                "worker_mode = single",
                "workers = 1",
                "",
                "[lmstudio]",
                "url = http://127.0.0.1:1234/v1/chat/completions",
                "model = lmstudio-model",
                "max_completion_tokens = 1000",
                "temperature = 0.0",
                "timeout_connect = 10",
                "timeout_read = 180",
                "max_retries = 3",
                "max_parse" + "_retries = 2",
                "image_format = png",
                "",
                "[image]",
                "max_width = 2560",
                "encode_quality = 85",
                "grayscale = True",
                "",
                "[validation]",
                "temp_min_f = 40.0",
                "temp_max_f = 140.0",
                "",
                "[pdf]",
                "dirty_lap_symbol = †",
                "show_dirty_lap_symbol = True",
                "",
                "[prompt]",
                f"active = {DEFAULT_PROMPT_ID}",
                "",
            ]
        ),
        encoding="utf-8",
    )



def test_config_file_service_saves_lmstudio_values_and_removes_legacy_keys(tmp_path) -> None:
    config_path = tmp_path / "forza_config.ini"
    _write_config(config_path)

    result = ConfigFileService(config_path).save_changes({
        "llm.model": "new-model",
        "llm.image_format": "webp",
        "llm.workers": "4",
    })

    assert result.ok is True
    cfg = load_config(config_path, strict=True)
    assert cfg.llm.model == "new-model"
    assert cfg.llm.image_format == "webp"
    assert cfg.workers == 4
    assert not hasattr(cfg, "benchmark_file")
    assert not hasattr(cfg.llm, "worker_mode")
    assert not hasattr(cfg.llm, "max_parse" + "_retries")

    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf-8")
    assert parser["lmstudio"]["model"] == "new-model"
    assert parser["llm"]["workers"] == "4"
    assert "max_workers" not in parser["llm"]
    assert "worker_mode" not in parser["llm"]
    assert "max_parse" + "_retries" not in parser["lmstudio"]
    assert "tracks_file" not in parser["paths"]
    assert "cars_file" not in parser["paths"]
    assert "benchmark_file" not in parser["paths"]
    assert ("raw_" + "artifacts_dir") not in parser["paths"]
    assert not parser.has_section("ol" + "lama")



def test_config_file_service_preview_rejects_invalid_pending_change(tmp_path) -> None:
    config_path = tmp_path / "forza_config.ini"
    _write_config(config_path)

    result = ConfigFileService(config_path).validate_changes({"image.max_width": "not-an-int"})

    assert result.ok is False
    assert "invalid literal" in result.message



def test_config_file_service_save_uses_atomic_replace_and_creates_unique_backup(tmp_path) -> None:
    config_path = tmp_path / "forza_config.ini"
    _write_config(config_path)

    service = ConfigFileService(config_path)
    first = service.save_changes({"user.gamertag": "First"})
    second = service.save_changes({"user.gamertag": "Second"})

    assert first.ok is True
    assert second.ok is True
    assert first.backup_path is not None and first.backup_path.exists()
    assert second.backup_path is not None and second.backup_path.exists()
    assert first.backup_path != second.backup_path
    assert not config_path.with_name(f"{config_path.name}.tmp").exists()
    assert load_config(config_path, strict=True).gamertag == "Second"
