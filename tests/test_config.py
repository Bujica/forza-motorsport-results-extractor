import pytest
from pathlib import Path
from forza.config import load_config, validate_config, CLASS_ORDER, AppConfig
from forza.exceptions import ConfigValidationError


# ─────────────────────── CLASS_ORDER ────────────────────────────────────────

class TestClassOrder:
    def test_all_expected_classes_present(self):
        for cls in ("E", "D", "C", "B", "A", "TCR", "S", "R", "P", "X", "Mixed", "Unknown"):
            assert cls in CLASS_ORDER

    def test_e_is_lowest(self):
        assert CLASS_ORDER["E"] == min(CLASS_ORDER.values())

    def test_unknown_is_highest(self):
        assert CLASS_ORDER["Unknown"] == max(CLASS_ORDER.values())

    def test_road_class_order(self):
        # E < D < C < B < A < TCR < S < R < P < X
        road = ["E", "D", "C", "B", "A", "TCR", "S", "R", "P", "X"]
        for i in range(len(road) - 1):
            assert CLASS_ORDER[road[i]] < CLASS_ORDER[road[i + 1]], \
                f"{road[i]} should come before {road[i+1]}"

    def test_mixed_before_unknown(self):
        assert CLASS_ORDER["Mixed"] < CLASS_ORDER["Unknown"]


# ─────────────────────── load_config ────────────────────────────────────────

class TestLoadConfig:
    def test_defaults_when_no_file(self, tmp_path):
        cfg = load_config(tmp_path / "nonexistent.ini")
        assert isinstance(cfg, AppConfig)
        assert cfg.gamertag == "Player"
        assert cfg.workers == 1
        assert cfg.llm.context_length == 5000
        assert cfg.llm.reasoning_mode == "off"
        assert cfg.llm.eval_batch_size == 1024
        assert not hasattr(cfg.llm, "worker_mode")
        assert not hasattr(cfg.llm, "max_parse" + "_retries")

    def test_reads_gamertag(self, tmp_path):
        p = tmp_path / "forza_config.ini"
        p.write_text("[user]\ngamertag = Bujica89\n", encoding="utf-8")
        cfg = load_config(p)
        assert cfg.gamertag == "Bujica89"

    def test_reads_lmstudio_section(self, tmp_path):
        p = tmp_path / "forza_config.ini"
        p.write_text("[lmstudio]\nmodel = local-model\n", encoding="utf-8")
        cfg = load_config(p)
        assert "1234" in cfg.llm.url
        assert cfg.llm.model == "local-model"

    def test_image_defaults(self, tmp_path):
        cfg = load_config(tmp_path / "nope.ini")
        assert cfg.image.max_width == 2560
        assert cfg.image.grayscale is True

    def test_image_config_values(self, tmp_path):
        p = tmp_path / "forza_config.ini"
        p.write_text("[image]\nmax_width = 1800\ngrayscale = false\n", encoding="utf-8")
        cfg = load_config(p)
        assert cfg.image.max_width == 1800
        assert cfg.image.grayscale is False

    def test_validation_defaults(self, tmp_path):
        cfg = load_config(tmp_path / "nope.ini")
        assert cfg.validation.temp_min_f == pytest.approx(40.0)
        assert cfg.validation.temp_max_f == pytest.approx(140.0)

    def test_paths_are_path_objects(self, tmp_path):
        cfg = load_config(tmp_path / "nope.ini")
        assert isinstance(cfg.input_dir, Path)
        assert isinstance(cfg.pdf_file, Path)
        assert not hasattr(cfg, "tracks_file")
        assert not hasattr(cfg, "cars_file")
        assert not hasattr(cfg, "benchmark_file")


    def test_llm_numeric_fields(self, tmp_path):
        p = tmp_path / "forza_config.ini"
        p.write_text(
            "[llm]\nworkers = 4\n"
            "[lmstudio]\nmax_completion_tokens = 800\ntemperature = 0.0\n"
            "max_retries = 3\n" + ("max_parse" + "_retries") + " = 2\n",
            encoding="utf-8")
        cfg = load_config(p)
        assert cfg.workers == 4
        assert cfg.llm.max_completion_tokens == 800
        assert cfg.llm.temperature == pytest.approx(0.0)
        assert cfg.llm.max_retries == 3
        assert not hasattr(cfg.llm, "worker_mode")
        assert not hasattr(cfg.llm, "max_parse" + "_retries")

    @pytest.mark.parametrize("key", ["context_length", "eval_batch_size", "physical_batch_size"])
    def test_strict_optional_lmstudio_ints_raise_config_validation_error(self, tmp_path, key):
        p = tmp_path / "forza_config.ini"
        p.write_text(f"[lmstudio]\n{key} = abc\n", encoding="utf-8")

        with pytest.raises(ConfigValidationError, match=key):
            load_config(p, strict=True)

    def test_lmstudio_reasoning_mode_accepts_on(self, tmp_path):
        p = tmp_path / "forza_config.ini"
        p.write_text("[lmstudio]\nreasoning_mode = on\n", encoding="utf-8")

        cfg = load_config(p, strict=True)
        validate_config(cfg)

        assert cfg.llm.reasoning_mode == "on"

    def test_pdf_dirty_lap_symbol_default(self, tmp_path):
        cfg = load_config(tmp_path / "nope.ini")
        assert cfg.pdf.dirty_lap_symbol == "\u2020"
        assert cfg.pdf.show_dirty_lap_symbol is True

    def test_database_file_default(self, tmp_path):
        cfg = load_config(tmp_path / "nope.ini")
        assert cfg.database_file == Path("data/forza.sqlite3")
        obsolete_raw_artifacts_key = "raw_" + "artifacts_dir"
        assert not hasattr(cfg, obsolete_raw_artifacts_key)

    def test_full_config_file_as_used_in_production(self, tmp_path):
        """Smoke test: the real forza_config.ini shape must load without error."""
        p = tmp_path / "forza_config.ini"
        p.write_text("""
[paths]
input_dir             = data/input
pdf_file              = output/reports/forza_bestlaps.pdf
log_file              = output/logs/forza_debug.log
database_file         = data/forza.sqlite3

[user]
gamertag = Bujica89

[llm]
workers = 1

[lmstudio]
url                   = http://127.0.0.1:1234/api/v1/chat
model                 = qwen/qwen3.5-9b
max_completion_tokens = 800
temperature           = 0.0
image_format          = png
timeout_connect       = 10
timeout_read          = 180
max_retries           = 3
context_length        = 5000
reasoning_mode        = off
eval_batch_size       = 1024
flash_attention       = true
offload_kv_cache_to_gpu = true

[prompt]
active = user_header_shaped_v1

[image]
max_width      = 2560
encode_quality = 100
grayscale      = true

[validation]
temp_min_f = 40
temp_max_f = 140

[pdf]
dirty_lap_symbol      = \u2020
show_dirty_lap_symbol = true
""", encoding="utf-8")
        cfg = load_config(p)
        assert cfg.gamertag == "Bujica89"
        assert cfg.workers == 1
        assert cfg.llm.model == "qwen/qwen3.5-9b"
        assert cfg.llm.context_length == 5000
        assert not hasattr(cfg.llm, "worker_mode")
        assert cfg.image.max_width == 2560
        assert cfg.image.encode_quality == 100
        assert cfg.image.grayscale is True
        assert cfg.validation.temp_min_f == pytest.approx(40.0)
        assert cfg.input_dir == Path("data/input")
        assert not hasattr(cfg, "benchmark_file")
        assert cfg.database_file == Path("data/forza.sqlite3")
        assert cfg.prompt.active == "user_header_shaped_v1"
        assert not hasattr(cfg.llm, "max_parse" + "_retries")
