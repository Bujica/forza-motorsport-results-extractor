from __future__ import annotations

"""Build the Windows beta portable bundle for the Rust line (0.1.0, active).

One-folder layout mirroring the Python bundle policy
(docs/release/beta_packaging.md): only product runtime files, explicit
allow-list, developer-only and private runtime material excluded.

Contents: forza.exe + forza-gui.exe (release), starter INI template,
reference data (cars/tracks/aliases), empty runtime folders, launch .bat
helpers, and a generated build_info.json. No Alembic migrations: the Rust
schema lives in code (forza-db) and `forza.exe maintenance db-upgrade`
creates/migrates the database.
"""

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tomllib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUST_DIR = ROOT / "forza-rust"
DIST_DIR = ROOT / "dist"
BUNDLE_DIR = DIST_DIR / "ForzaMotorsportResultsExtractor-Rust"
RELEASE_DIR = RUST_DIR / "target" / "release"
BETA_LABEL = "beta.1"
PLATFORM_LABEL = "windows-x64"

# Reuse the exact same forbidden lists as the Python bundle so both lines
# obey one policy (tools/build_windows_beta.py has no import side effects).
_TOOLS_SPEC = importlib.util.spec_from_file_location(
    "_beta_policy", ROOT / "tools" / "build_windows_beta.py"
)
if _TOOLS_SPEC is None or _TOOLS_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("Unable to load bundle policy from tools/build_windows_beta.py")
_TOOLS = importlib.util.module_from_spec(_TOOLS_SPEC)
_TOOLS_SPEC.loader.exec_module(_TOOLS)
FORBIDDEN_BUNDLE_NAMES = _TOOLS.FORBIDDEN_BUNDLE_NAMES
FORBIDDEN_BUNDLE_FILES = _TOOLS.FORBIDDEN_BUNDLE_FILES

BINARIES = ("forza.exe", "forza-gui.exe")

# Explicit allow-list: relative source -> bundle destination. Anything not
# listed here never enters the bundle. No .bat helpers ship: first launch is
# self-sufficient (config/database/folders are created by the app itself),
# and RUST_BETA.md is the single operator manual.
RUNTIME_FILES = (
    "forza_config.ini.example",
    "RUST_BETA.md",
    "cars.txt",
    "tracks.txt",
    "data/external/track_aliases.json",
)

RUNTIME_DIRS = (
    "data/input",
    "data/external",
    "output/reports",
    "output/logs",
    "output/exports",
)


def _rust_version() -> str:
    with (RUST_DIR / "Cargo.toml").open("rb") as handle:
        workspace = tomllib.load(handle)
    return str(workspace["workspace"]["package"]["version"])


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


def _run(command: list[str], cwd: Path) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def _write_text(path: Path, text: str, *, crlf: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    newline = "\r\n" if crlf else "\n"
    path.write_text(text, encoding="utf-8", newline=newline)


def _copy_into_bundle(relative_path: str) -> None:
    source = ROOT / relative_path
    if not source.exists():
        raise FileNotFoundError(f"Required beta runtime file is missing: {relative_path}")
    destination = BUNDLE_DIR / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _create_bundle_tree() -> None:
    if BUNDLE_DIR.exists():
        shutil.rmtree(BUNDLE_DIR)
    for relative_dir in RUNTIME_DIRS:
        (BUNDLE_DIR / relative_dir).mkdir(parents=True, exist_ok=True)
    for binary in BINARIES:
        source = RELEASE_DIR / binary
        if not source.exists():
            raise FileNotFoundError(
                f"Release binary missing: {source} (run: cargo build --release -p forza-cli -p forza-gui)"
            )
        destination = BUNDLE_DIR / binary
        shutil.copy2(source, destination)
    for relative_path in RUNTIME_FILES:
        _copy_into_bundle(relative_path)


def _write_build_info() -> None:
    payload = {
        "app_name": "Forza Motorsport Results Extractor",
        "version": _rust_version(),
        "package_version": _rust_version(),
        "channel": "beta",
        "line": "rust",
        "target_game": "Forza Motorsport, 2023 release",
        "target_screen": "post-race Results screen",
        "commit": _git_commit(),
        "built_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        ),
        "platform": PLATFORM_LABEL,
    }
    _write_text(BUNDLE_DIR / "build_info.json", json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _assert_clean_bundle() -> None:
    if not BUNDLE_DIR.exists():
        raise RuntimeError(f"Rust bundle output not found: {BUNDLE_DIR}")
    for path in BUNDLE_DIR.rglob("*"):
        rel = path.relative_to(BUNDLE_DIR).as_posix()
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


def build(*, skip_cargo: bool = False) -> Path:
    if skip_cargo:
        print("Skipping cargo build; using existing forza-rust/target/release binaries.")
    else:
        _run(
            ["cargo", "build", "--release", "-p", "forza-cli", "-p", "forza-gui"],
            cwd=RUST_DIR,
        )
    _create_bundle_tree()
    _write_build_info()
    _assert_clean_bundle()

    zip_name = f"ForzaMotorsportResultsExtractor-rust-{_rust_version()}-{BETA_LABEL}-{PLATFORM_LABEL}.zip"
    zip_path = DIST_DIR / zip_name
    _zip_dir(BUNDLE_DIR, zip_path)
    print(f"Rust beta bundle written: {zip_path}")
    return zip_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Windows Rust beta portable bundle.")
    parser.add_argument(
        "--skip-cargo",
        action="store_true",
        help="reuse existing forza-rust/target/release binaries",
    )
    args = parser.parse_args()
    build(skip_cargo=args.skip_cargo)


if __name__ == "__main__":
    main()
