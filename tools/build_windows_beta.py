from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
SPEC_FILE = ROOT / "packaging" / "forza_motorsport_results_extractor_windows.spec"
PYINSTALLER_OUTPUT = DIST_DIR / "ForzaMotorsportResultsExtractor"
BETA_LABEL = "beta.1"
PLATFORM_LABEL = "windows-x64"
FORBIDDEN_BUNDLE_NAMES = {
    ".git",
    ".github",
    "scripts",
    "tests",
    "tools",
    "__pycache__",
    ".pytest_cache",
}
FORBIDDEN_BUNDLE_FILES = {
    "data/forza.sqlite3",
    "data/forza.sqlite3-shm",
    "data/forza.sqlite3-wal",
    "data/external/DataFM.xlsx",
    "data/external/UniqueFM.xlsx",
}


def _version() -> str:
    from forza.version import __version__

    return __version__


def _run(command: list[str]) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _copy_runtime_file(relative_path: str) -> None:
    source = ROOT / relative_path
    if not source.exists():
        raise FileNotFoundError(f"Required beta runtime file is missing: {relative_path}")
    destination = PYINSTALLER_OUTPUT / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _config_template() -> str:
    install_path = ROOT / "install.py"
    spec = importlib.util.spec_from_file_location("_forza_install_helper", install_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load config template from {install_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    template = getattr(module, "_CONFIG_TEMPLATE", None)
    if not isinstance(template, str) or not template.strip():
        raise RuntimeError(f"Config template not found in {install_path}")
    return template



def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _write_build_info() -> None:
    from forza.app_info import (
        APP_NAME,
        APP_RELEASE,
        APP_SHORT_NAME,
        BUILD_INFO_FILENAME,
        TARGET_GAME,
        TARGET_SCREEN,
    )

    payload = {
        "app_name": APP_NAME,
        "short_name": APP_SHORT_NAME,
        "version": APP_RELEASE,
        "package_version": _version(),
        "channel": "beta",
        "target_game": TARGET_GAME,
        "target_screen": TARGET_SCREEN,
        "commit": _git_commit(),
        "built_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "platform": PLATFORM_LABEL,
    }
    _write_text(
        PYINSTALLER_OUTPUT / BUILD_INFO_FILENAME,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )

def _create_runtime_scaffold() -> None:
    for relative_dir in (
        "data/input",
        "data/external",
        "output/reports",
        "output/logs",
        "output/exports",
    ):
        (PYINSTALLER_OUTPUT / relative_dir).mkdir(parents=True, exist_ok=True)

    _write_text(PYINSTALLER_OUTPUT / "forza_config.ini.example", _config_template())
    _copy_runtime_file("README_BETA.md")
    _copy_runtime_file("cars.txt")
    _copy_runtime_file("tracks.txt")
    _copy_runtime_file("data/external/track_aliases.json")

    _write_text(
        PYINSTALLER_OUTPUT / "Initialize Database.bat",
        '@echo off\r\n"%~dp0fmre-cli.exe" maintenance db-upgrade\r\npause\r\n',
    )
    _write_text(
        PYINSTALLER_OUTPUT / "DB Doctor.bat",
        '@echo off\r\n"%~dp0fmre-cli.exe" maintenance db-doctor --json\r\npause\r\n',
    )
    _write_text(
        PYINSTALLER_OUTPUT / "Config Check.bat",
        '@echo off\r\n"%~dp0fmre-cli.exe" config-check\r\npause\r\n',
    )


def _remove_forbidden_bundle_artifacts() -> None:
    """Remove non-product cache artifacts copied by PyInstaller data collection."""
    if not PYINSTALLER_OUTPUT.exists():
        return
    for cache_dir in sorted(PYINSTALLER_OUTPUT.rglob("__pycache__"), reverse=True):
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir)
    for pattern in ("*.pyc", "*.pyo"):
        for cache_file in PYINSTALLER_OUTPUT.rglob(pattern):
            if cache_file.is_file():
                cache_file.unlink()


def _assert_clean_bundle() -> None:
    if not PYINSTALLER_OUTPUT.exists():
        raise RuntimeError(f"PyInstaller output not found: {PYINSTALLER_OUTPUT}")
    for path in PYINSTALLER_OUTPUT.rglob("*"):
        rel = path.relative_to(PYINSTALLER_OUTPUT).as_posix()
        if path.name in FORBIDDEN_BUNDLE_NAMES:
            raise RuntimeError(f"Forbidden developer-only path in beta bundle: {rel}")
        if rel in FORBIDDEN_BUNDLE_FILES:
            raise RuntimeError(f"Forbidden local/private runtime file in beta bundle: {rel}")


def _zip_dir(source_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir.parent))


def build(*, skip_pyinstaller: bool = False) -> Path:
    if not SPEC_FILE.exists():
        raise FileNotFoundError(SPEC_FILE)

    if skip_pyinstaller:
        print("Skipping PyInstaller; using existing dist/ForzaMotorsportResultsExtractor directory.")
    else:
        _run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(SPEC_FILE)])

    _create_runtime_scaffold()
    _write_build_info()
    _remove_forbidden_bundle_artifacts()
    _assert_clean_bundle()

    zip_name = f"ForzaMotorsportResultsExtractor-{_version()}-{BETA_LABEL}-{PLATFORM_LABEL}.zip"
    zip_path = DIST_DIR / zip_name
    _zip_dir(PYINSTALLER_OUTPUT, zip_path)
    print(f"Beta bundle written: {zip_path}")
    return zip_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Windows beta portable bundle.")
    parser.add_argument("--skip-pyinstaller", action="store_true", help="reuse an existing dist/ForzaMotorsportResultsExtractor directory")
    args = parser.parse_args()
    build(skip_pyinstaller=args.skip_pyinstaller)


if __name__ == "__main__":
    main()
