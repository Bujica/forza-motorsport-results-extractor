# User Guide

Status: current
Audience: user
Lifecycle: permanent
Scope: External behavior
Last verified: 2026-06-18
Supersedes: `docs/USER_GUIDE.md`
Related tests: manual GUI workflow checks

This guide explains how to use Forza Motorsport Results Extractor from the
operator perspective. It avoids internal code contracts; those live under
`docs/contracts/`.


## Supported input scope

Forza Motorsport Results Extractor targets screenshots from the post-race Results screen in Forza Motorsport, 2023 release. The beta does not target Forza Horizon, older Motorsport layouts, leaderboard-only screens, telemetry overlays, or arbitrary racing-game screenshots.

## Overview

The application processes Forza Motorsport race-result screenshots, stores
state in SQLite, and produces user-facing reports and exports.

The GUI is the recommended interface. CLI commands are intentionally limited
to automation, maintenance, and controlled reruns.

Runtime source of truth:

```text
data/forza.sqlite3
```

Normal extraction does not move, rename, or delete source screenshots.

## First Run

1. Install dependencies.
2. Start LM Studio.
3. Configure `forza_config.ini`.
4. Upgrade or create the database explicitly.
5. Open the GUI.

Commands:

```bash
python install.py
pip install -e .[dev,gui]
python -m forza maintenance db-upgrade
python -m forza maintenance db-doctor --json
python -m forza gui
```

## GUI Sections

```text
Images           input-folder inventory, selection, preview, flags, rename, export, deletion
Process          selected extraction runs, progress, and operator log
Review           review queue and correction workflow
Best Laps        best-lap frontier, external-record import, PDF, and CSV
Records          performance records, community coverage, cars, progress, and rivals
Diagnostics      runtime overview, image debug, DB Doctor, and logs
Settings         validated configuration editor
```

## Process

Use `Images` first for normal GUI operation: confirm the files in the configured
input folder, select the screenshots to process, then run the selected images.

Use `Process` to configure selected runs, watch progress, and read the operator
event log. GUI extraction starts from `Images` with `Process selected`. Use
`Run input folder` in `Process` only when you intentionally want the whole
configured input folder. Full-folder runs also remain available through the CLI
commands below.

Common CLI equivalents:

```bash
python -m forza
python -m forza --limit 5
python -m forza --dry-run
python -m forza --force
python -m forza --retry-errors
python -m forza rebuild
python -m forza export
```

`--limit N` processes only the first supported input screenshots by file modified time.
Use it for reduced validation runs without moving screenshots out of the input
folder.

`--dry-run` records a preview run and run-input decisions without model calls or
new extraction results.

Normal processing waits for LM Studio to report that the configured model is
loaded with compatible runtime settings before registering new images or
starting extraction. If LM Studio cannot load or validate the model, the run
fails as an operational backend error and screenshots are not marked as failed
extractions.

`--force` reprocesses all images currently in the configured input folder.

`--retry-errors` reprocesses only images whose latest extraction result is
`error` and whose file is still available in SQL and in the configured input
folder. Use it after fixing an operational problem such as LM Studio running with
no model loaded. The same mode is available in the GUI Process screen as `Retry
errors`.

`rebuild` recomputes derived relational state without model calls. It does not
import external spreadsheets or generate a PDF; those are explicit Best Laps
actions.

## Settings

The Settings page validates pending values before saving. Saving creates a
timestamped backup of `forza_config.ini` and writes through a temporary file.

Important settings include:

- LM Studio model.
- Prompt.
- Input, PDF, and log paths. Database state is shown in the status
  bar and DB Doctor instead of Settings.
- Image format, max width, quality, and grayscale.
- Context length, reasoning mode, batch settings, max tokens, temperature, and
  read timeout.
- Worker count. Keep `[llm] workers = 1` as the safe LM Studio default unless
  local validation shows a higher value is stable for the selected model and
  hardware.

Config-sensitive GUI pages update from the saved config without restarting the
application.

## Review

Use `Review` for SQL-backed review cases. Review decisions are persisted to the
database. The application no longer uses manual override JSON as the runtime
review mechanism.

Keyboard review flow:

- `Up` / `Down` move through the review queue.
- `Left` / `Right` switch the selected primary action for binary reviews such
  as dirty/clean or rain/dry.
- `Enter` applies the selected primary action and advances to the next case.

Review state should be treated as part of runtime data. Rebuild outputs after
meaningful review changes before trusting reports.

Review uses field-level reasons: `dirty_lap`, `track`, `weather`,
`race_class`, `car`, and `driver_name`. Details such as unknown track,
ambiguous layout, unknown weather, missing car reference, empty driver name,
invalid driver-name shape, or numeric driver-name prefix are shown as triggers.

Resolved review cases keep the model value, corrected value, decision field,
and outcome. `confirmed` means the model value was kept. `model_error` means
the operator corrected the database and the case becomes evidence for prompt,
normalization, parser, reference, or model improvements.

## Images

Use `Images` to inspect the configured input folder, synchronize image-file
state, select files for processing, and inspect image state. Supported image
files can appear here before they have extraction results.

Run filters display descriptive run labels, but filtering still uses the
stable internal `run_id`.

Supported actions include:

- Select one or more image files and process only that selection.
- Preview image and extraction evidence.
- Rescan selected files against the filesystem.
- Rename or export selected files explicitly.
- Delete selected image assets explicitly.

Normal extraction never deletes source files. Physical deletion is limited to
the explicit Delete action. When a selected file still exists inside the
configured `input_dir`, the file is removed and the related image database
records are removed with it. If the file was already missing, Delete still
cleans the image database records.

Files outside the configured `input_dir` are never physically deleted by the
Images delete action.

## Image Flags

Image flags are review and inventory annotations such as duplicate content or
model-suspicious fields. For model quality work, use resolved Review cases with
`outcome=model_error`.

## Best Laps

The Best Laps page reads the persisted best-lap frontier from SQLite. It does
not compute a hidden fallback from all lap rows.

Best-lap recomputation is explicit. Run rebuild/recompute before treating the
screen as authoritative after review or source-data changes. Rebuild does not
generate PDF output automatically.

The configured gamertag appears in the filter bar. Use `Only this driver` to
show only that player's laps. Use `Source` only to choose screenshots, external
records, or both.

Use the Best Laps action buttons for output and external records:

```text
Import spreadsheet  imports external leaderboard rows and reloads Best Laps
Generate PDF        writes the currently filtered table rows to the PDF
Open last PDF       opens the configured PDF file
Export CSV          writes the currently filtered table rows to CSV
```

The PDF report is written to:

```text
output/reports/forza_bestlaps.pdf
```

## External Records

External leaderboard records are not screenshot lap rows. They are imported into
SQLite as a normalized external-record dataset and displayed alongside screenshot
records for comparison.

Supported flow:

```text
data/external/DataFM.xlsx
  -> Best Laps > Import spreadsheet
  -> active external-record snapshot in SQLite, replacing the previous active snapshot
  -> Best Laps table, filtered PDF, and filtered CSV
```

External rows use `Source = External`, no image detail link, no temperature, dry
weather by contract, and the same external-record highlight used by the PDF.

Spreadsheet track aliases are read from:

```text
data/external/track_aliases.json
```

Missing aliases, invalid rows, malformed files, invalid lap times, unmapped
tracks, and missing required columns are reported as controlled import issues.
Rejected rows are reported separately from warnings such as canonicalized or new
car names.

Imported car names are canonicalized against the active `reference_cars` table.
Known spelling differences are rewritten to the canonical car name, ambiguous
matches are left unchanged and reported, and new car names from valid spreadsheet
rows are added to `reference_cars` even when they are not the final best external
time for a track/class group.

## Records

Use `Records` for player-centric performance analysis. The table is grouped by
track, class, and weather, and shows your best lap, the fastest rival seen in
your shared clean-lap contexts, dry non-TCR community-record coverage from Best
Laps external records, most-used cars, dominant cars, progress history, and
rivals matching the active Records filters. Rival and community gaps are shown as
absolute time plus relative percentage where a comparison lap exists.

Community comparisons are available only for dry non-TCR combinations because
the imported spreadsheet represents dry leaderboard records and does not include
TCR. External spreadsheet import remains in Best Laps; Records summarizes the
imported data but does not own the import action.

## Diagnostics

The `Diagnostics` GUI section is the advanced operator area for reproducible
runtime overview, image debug, DB Doctor, and logs. Former Lab/workbench and
benchmark surfaces are not public product tools.

In Image Debug, `Model Response` shows raw model-response evidence, `Parsed Data`
shows structured extraction data, and `Image Metadata` shows screenshot physical
metadata such as dimensions, format, MIME type, size, race date, and metadata JSON.

Read the dedicated tutorial:

```text
docs/user/advanced_tools.md
```

## Maintenance

Use maintenance commands when the database or runtime artifacts need explicit
operator action.

```bash
python -m forza maintenance db-status
python -m forza maintenance db-upgrade
python -m forza maintenance db-doctor
python -m forza maintenance db-doctor --json
python -m forza maintenance db-reset --yes
```

`db-upgrade` is explicit for CLI maintenance. GUI startup may prompt before
creating/upgrading a missing or outdated database, and may offer a confirmed
reset when the configured database is incompatible with the current schema.

`db-doctor` is the integrity screen before clean reruns, releases, or serious
troubleshooting conclusions. It is read-only and verifies run/input/result counters,
schema state, artifact integrity, prompt snapshots, Review identity, and related
runtime contracts. Review identity repair is no longer a public CLI workflow;
maintainers should treat it as an internal service-level recovery path.
