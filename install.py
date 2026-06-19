"""
Forza Motorsport Results Extractor — Install helper
Version: 1.1 (2026-06-04)

Verifies the environment, creates runtime folders, creates the configuration
example when missing, and installs the editable GUI package.

Usage:
    python install.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MIN_PYTHON = (3, 10)
BASE = Path(__file__).parent

REQUIRED_DIRS = [
    BASE / "data",                                   # parent dir for SQLite DB
    BASE / "data" / "input",
    BASE / "data" / "external",
    BASE / "output" / "reports",
    BASE / "output" / "logs",
    BASE / "output" / "exports",
]

_CONFIG_TEMPLATE = """# Forza Motorsport Results Extractor - Configuration
# SQLite DB vNext is the runtime source of truth.

[paths]
input_dir             = data/input
pdf_file              = output/reports/forza_bestlaps.pdf
log_file              = output/logs/forza_debug.log
database_file         = data/forza.sqlite3

[user]
gamertag = Player

[llm]
workers = 1

[prompt]
active = user_header_shaped_v1

# ============================================================
# LM Studio native REST settings.
# The model name must match exactly what appears in your
# LM Studio model list.
# ============================================================

[lmstudio]
url               = http://127.0.0.1:1234/api/v1/chat
model             = qwen/qwen3.5-9b
max_completion_tokens = 800
temperature       = 0.0
image_format          = png
timeout_connect   = 10
timeout_read      = 180
max_retries       = 3
context_length    = 5000
reasoning_mode    = off
eval_batch_size   = 1024
physical_batch_size =
flash_attention   = true
offload_kv_cache_to_gpu = true
performance_tps_floor = 20.0
performance_reload_elapsed_s = 45.0
performance_reload_streak = 3

[image]
# Default extraction image settings. Tune after validating results on your hardware.
max_width      = 2560
encode_quality = 100
grayscale      = true

[validation]
temp_min_f = 40
temp_max_f = 140

[pdf]
dirty_lap_symbol      = †
show_dirty_lap_symbol = true
"""


def _check_python() -> bool:
    v = sys.version_info[:2]
    if v < MIN_PYTHON:
        print(f"  FAIL  Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required "
              f"(found {v[0]}.{v[1]})")
        return False
    print(f"  OK    Python {v[0]}.{v[1]}")
    return True


def _create_dirs() -> None:
    for d in REQUIRED_DIRS:
        d.mkdir(parents=True, exist_ok=True)
    print(f"  OK    Folder structure verified ({len(REQUIRED_DIRS)} directories)")


def _create_config_example() -> None:
    example = BASE / "forza_config.ini.example"
    if example.exists():
        print("  SKIP  forza_config.ini.example already exists")
        return
    example.write_text(_CONFIG_TEMPLATE, encoding="utf-8")
    print("  OK    forza_config.ini.example created")


def _install_package() -> bool:
    print("\nInstalling package dependencies...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".[gui]"],
        capture_output=False,
    )
    if result.returncode != 0:
        print("\n  FAIL  pip install failed — check output above")
        return False
    print("\n  OK    Package installed")
    return True


def _check_config() -> None:
    cfg = BASE / "forza_config.ini"
    if not cfg.exists():
        print("  WARN  forza_config.ini not found.")
        print("        Copy forza_config.ini.example and set your gamertag + model.")
    else:
        import configparser
        c = configparser.ConfigParser()
        c.read(cfg, encoding="utf-8")
        gamertag = c.get("user", "gamertag", fallback="Player")
        model = c.get("lmstudio", "model", fallback="")
        workers = c.get("llm", "workers", fallback="1")
        if gamertag == "Player":
            print("  WARN  gamertag is still 'Player' — set it in forza_config.ini")
        else:
            print(f"  OK    gamertag = {gamertag}")
        if not model:
            print("  WARN  model is not set in forza_config.ini")
        else:
            print(f"  OK    model    = {model}")
        print(f"  OK    workers  = {workers}")


def main() -> None:
    print("=" * 50)
    print("Forza Motorsport Results Extractor — Setup")
    print("=" * 50)

    print("\nChecking Python version...")
    if not _check_python():
        sys.exit(1)

    print("\nCreating folder structure...")
    _create_dirs()

    print("\nCreating config example...")
    _create_config_example()

    ok = _install_package()
    if not ok:
        sys.exit(1)

    print("\nChecking configuration...")
    _check_config()

    print("\n" + "=" * 50)
    print("Setup complete.")
    print()
    print("Next steps:")
    print("  1. Confirm LM Studio is running with a vision model loaded")
    print("  2. Copy forza_config.ini.example to forza_config.ini if needed")
    print("  3. Edit forza_config.ini — set gamertag and confirm model name")
    print("  4. Run: python -m forza maintenance db-upgrade   (creates the database)")
    print("  5. Run: python -m forza maintenance db-doctor")
    print("  6. Copy screenshots to data/input/")
    print("  7. Run: python -m forza --limit 5   (smoke test)")
    print("=" * 50)


if __name__ == "__main__":
    main()
