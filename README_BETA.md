
# Forza Motorsport Results Extractor Beta Guide

This guide is for testers using the Windows beta bundle.

## Scope

- Product: Forza Motorsport Results Extractor.
- Release: `0.20.0-beta.1`.
- Target game: Forza Motorsport, 2023 release.
- Target screenshot type: post-race Results screen.
- Platform: Windows.
- Model runtime: user-managed local LM Studio endpoint.

The beta does not support Forza Horizon, older Motorsport layouts, leaderboard screenshots, telemetry overlays, or arbitrary racing-game screenshots.

## What is included

The ZIP bundle includes:

- `Forza Motorsport Results Extractor.exe` for the GUI.
- `fmre-cli.exe` for maintenance commands.
- Alembic migrations and required runtime package files.
- `forza_config.ini.example`.
- `README_BETA.md`.
- `cars.txt`, `tracks.txt`, and `data/external/track_aliases.json`.
- Empty runtime folders such as `data/input`, `output/reports`, `output/logs`, and `output/exports`.
- `build_info.json` with beta build metadata.

## What is not included

The ZIP bundle does not include:

- LM Studio.
- Model weights.
- real `data/forza.sqlite3` databases.
- input screenshots.
- generated reports, logs, exports, prompt diagnostics, or debug artifacts.
- private spreadsheets such as `DataFM.xlsx` or `UniqueFM.xlsx`.
- developer-only directories such as `tools/`, `scripts/`, `tests/`, `.git/`, or `.github/`.

## First run

The bundle includes `Initialize Database.bat` as a shortcut for `fmre-cli.exe maintenance db-upgrade`.
Use it before the first GUI run, or whenever the portable database was deleted/recreated.

Unzip the beta package to a writable folder. Avoid running it directly from the ZIP viewer.

From the unpacked bundle folder:

```cmd
copy forza_config.ini.example forza_config.ini
fmre-cli.exe maintenance db-upgrade
fmre-cli.exe maintenance db-doctor --json
"Forza Motorsport Results Extractor.exe"
```

Expected DB Doctor result after initialization:

```json
{
  "schema_state": "current",
  "ok": true
}
```

If DB Doctor reports `schema_state: missing`, run `fmre-cli.exe maintenance db-upgrade` first.

## Input folder

Place screenshots in the bundle-local input folder:

```text
data\input
```

The expected screenshots are from the Forza Motorsport post-race Results screen. Other screens may scan as files, but they are outside the supported extraction target and may fail review or extraction.

The source checkout has its own `data\input`. The beta bundle does not read from the source checkout unless you explicitly configure it to do so.

## LM Studio setup

LM Studio and model weights are not bundled. Start LM Studio separately, load a compatible vision model, and confirm the local server endpoint configured in `forza_config.ini`.

Typical checks:

```cmd
fmre-cli.exe config-check
fmre-cli.exe maintenance db-doctor --json
```

## GUI workflow

1. Open `Forza Motorsport Results Extractor.exe`.
2. Go to **Settings** and verify paths, backend, model, and prompt settings.
3. Put supported screenshots in `data\input`.
4. Go to **Images** and use **Scan input folder**.
5. Select images and process them.
6. Use **Review** for corrections.
7. Use **Best Laps** and **Records** for output/analysis.
8. Use **Diagnostics** for DB Doctor, Image Debug, and logs.

## Support information

Use the GUI About dialog to copy diagnostics when reporting an issue. Include:

- app version.
- build commit and build time from `build_info.json`, if present.
- DB Doctor JSON.
- whether the issue occurs in the source checkout, the beta bundle, or both.
- whether screenshots are in the bundle-local `data\input` folder.

Do not attach private screenshots unless you intend to share their contents publicly.

## Legal notice

Independent community project. Not affiliated with Microsoft, Xbox, Turn 10 Studios, or the Forza Motorsport franchise.
