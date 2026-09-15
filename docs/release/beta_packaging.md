# Windows Beta Packaging

Status: current — Python line (`0.21.0` final, legacy). A Rust (`0.1.0`)
bundle policy does not exist yet; when created, it must mirror the
one-folder + explicit allow-list rules below.
Target game: Forza Motorsport, 2023 release.
Target screenshot type: post-race Results screen.

Audience: maintainer
Lifecycle: beta release
Scope: Windows portable executable packaging
Last verified: 2026-06-19

## Goal

Build a portable Windows beta ZIP that testers can unpack and run without a source checkout.
The bundle must include only product runtime files and must exclude developer-only directories.

## Bundle policy

Included:

- `Forza Motorsport Results Extractor.exe` for GUI-first testing.
- `fmre-cli.exe` for explicit maintenance commands.
- Alembic migrations and runtime package files required by the application.
- `forza_config.ini.example`.
- `README_BETA.md`.
- `cars.txt`, `tracks.txt`, and `data/external/track_aliases.json`.
- Empty runtime folders for `data/input`, `output/reports`, `output/logs`, and `output/exports`.

Excluded:

- `tools/`.
- `scripts/`.
- `tests/`.
- `.git/`.
- `.github/`.
- real SQLite databases.
- local screenshots, logs, reports, exports, prompt diagnostics, and debug artifacts.
- private external spreadsheets such as `DataFM.xlsx`.

## Local build

```cmd
pip install -e .[dev,gui,build]
python tools\build_windows_beta.py
```

Expected artifact:

```text
dist\ForzaMotorsportResultsExtractor-0.21.0-beta.1-windows-x64.zip
```

## Smoke test

From the unpacked bundle:

```cmd
fmre-cli.exe --help
fmre-cli.exe maintenance db-upgrade
fmre-cli.exe maintenance db-doctor --json
"Forza Motorsport Results Extractor.exe"
```

## Notes

The beta uses PyInstaller one-folder packaging. This is deliberate: PySide6, SQLite/Alembic data files, and troubleshooting are easier to validate before attempting a one-file executable.

## Rust bundle (current line, `0.1.0`)

Policy: same one-folder + explicit allow-list rules as above. The Rust
bundle is built by `packaging/build_windows_beta_rust.py` (validated by
`tests/test_beta_packaging_rust_static.py`, released by
`.github/workflows/build-windows-beta-rust.yml`):

```cmd
python packaging\build_windows_beta_rust.py
```

Expected artifact:

```text
dist\ForzaMotorsportResultsExtractor-rust-0.1.0-beta.1-windows-x64.zip
```

Contents: `forza.exe` + `forza-gui.exe` (release), starter
`forza_config.ini.example`, `RUST_BETA.md` (the single operator manual),
`cars.txt`, `tracks.txt`, `data/external/track_aliases.json`, empty
`data/input` and `output/` folders, and a generated `build_info.json`.
No `.bat` helpers ship: first launch is self-sufficient (the app creates
the config from the example, the database, and missing folders itself).
No Alembic migrations ship: the Rust schema lives in
code (`forza-db`) and `forza.exe maintenance db-upgrade` creates/migrates
the database. The forbidden name/file lists are imported from
`tools/build_windows_beta.py`, so both lines obey one policy.

Smoke test from the unpacked bundle (or just open the GUI — setup is
automatic):

```cmd
forza.exe --version
forza.exe maintenance db-upgrade
forza.exe maintenance db-doctor --json
forza-gui.exe
```
