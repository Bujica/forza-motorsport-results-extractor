
# Forza Motorsport Results Extractor

Forza Motorsport Results Extractor is a Windows desktop tool for extracting lap-time data from Forza Motorsport results-screen screenshots using a local LM Studio vision model.

Status: public beta. The current release target is `0.20.0-beta.1`.

## Target and support scope

- Game: Forza Motorsport, 2023 release.
- Screenshot type: post-race Results screen.
- Platform: Windows.
- Processing mode: local-first, using the LM Studio endpoint configured by the user.

The beta does not target Forza Horizon, older Forza Motorsport layouts, leaderboard screens, telemetry overlays, or arbitrary racing-game screenshots. If the game UI changes, extraction prompts and review workflows may need adjustment.

## What it does

- Scans an input folder for Forza Motorsport results-screen screenshots.
- Extracts lap-time, car, class, track, weather, driver, and related race-result data through a local vision model.
- Stores runtime data in SQLite.
- Provides a GUI-first workflow for image inventory, processing, review, best laps, records, diagnostics, and settings.
- Generates best-lap reports and CSV exports.
- Imports and compares community records when external record data is provided by the user.

## What it does not do

- Does not include LM Studio.
- Does not include model weights.
- Does not upload screenshots to a cloud OCR or hosted model service by default.
- Does not auto-collect telemetry.
- Does not support Forza Horizon.
- Does not support older Forza Motorsport UI layouts as a product target.

## Windows beta bundle

The beta bundle is a one-folder Windows distribution intended for testers. It includes the GUI executable, CLI maintenance executable, migrations, runtime reference data, and starter configuration templates.

Expected artifact name:

```text
ForzaMotorsportResultsExtractor-0.20.0-beta.1-windows-x64.zip
```

The beta application bundle must not include developer-only or private runtime material. In particular, `tools/`, `scripts/`, `tests/`, `.git/`, and `.github/` must not be copied into beta application bundles.

The bundle also excludes real local databases, input screenshots, logs, reports, exports, prompt diagnostics, debug artifacts, and private spreadsheets such as `DataFM.xlsx` or `UniqueFM.xlsx`.

See [README_BETA.md](README_BETA.md) for tester setup instructions.

## Source install

From a source checkout:

```cmd
pip install -e ".[dev,gui]"
python -m forza maintenance db-upgrade
python -m forza maintenance db-doctor --json
python -m forza gui
```

Normal CLI processing is still available for operational use:

```cmd
python -m forza --help
python -m forza --version
python -m forza run --limit 5
```

The GUI is the primary product surface. The CLI is retained for operational commands such as database setup, validation, and controlled processing.

## Runtime data

Runtime state is stored under the configured local data paths. The default local SQLite database is:

```text
data/forza.sqlite3
```

Do not commit local databases, screenshots, logs, reports, prompt diagnostics, exported artifacts, or private spreadsheets.

## Privacy model

Forza Motorsport Results Extractor is local-first. Screenshots are read from local folders and processed through the LM Studio endpoint configured in `forza_config.ini`. The project does not require a hosted OCR service and does not bundle a model.

Users are responsible for the model they run, the endpoint they configure, and the screenshots they choose to process.

## Documentation

- [Quick Guide](QUICK_GUIDE.md)
- [Beta tester guide](README_BETA.md)
- [Roadmap](docs/roadmap.md)
- [Beta packaging policy](docs/release/beta_packaging.md)

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).

## Legal notice

Independent community project. Not affiliated with Microsoft, Xbox, Turn 10 Studios, or the Forza Motorsport franchise.

## Target

- Primary input: Forza Motorsport (2023 release) post-race Results screen screenshots.
- This beta is not intended for Forza Horizon, older Motorsport layouts, leaderboard screens, or arbitrary racing-game screenshots.
