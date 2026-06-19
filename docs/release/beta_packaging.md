# Windows Beta Packaging

Status: current
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
dist\ForzaMotorsportResultsExtractor-0.20.0-beta.1-windows-x64.zip
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
