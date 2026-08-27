Status: historical
Audience: developer, maintainer, LLM
Lifecycle: temporary (superseded by `migration_report.md` in this directory)
Scope: detailed porting analysis of `forza-rust/crates/forza-cli` crate
Last verified: 2026-08-27
Supersedes: none

# Detailed porting analysis — forza-cli

## Overview

CLI interface for the Forza Motorsport Results Extractor. Uses `clap` for argument parsing and delegates to five supporting Rust crates: `forza-config`, `forza-db`, `forza-app`, `forza-gui`, `forza-pipeline`, `forza-output`. Contains exactly one source file: `src/main.rs` (462 lines).

| File | Lines | Python Source | Status |
|------|-------|--------------|--------|
| `src/main.rs` | 462 | `cli/main.py`, `cli/parser.py`, `cli/run.py`, `cli/rebuild.py`, `cli/export.py`, `cli/maintenance.py`, `cli/gui.py` | **Partially ported** |

## CLI Argument Structure (`Cli`, `Command`, `MaintenanceCommand`)

Python reference: `forza/cli/parser.py::build_parser()`.

| Rust | Python | Status |
|------|--------|--------|
| `--config` (default: `forza_config.ini`) | `--config` (default: `forza_config.ini`) | Fully ported |
| `Command::Gui` subcommand | `gui` subparser | Fully ported |
| `Command::Run { dry_run, force, retry_errors, limit }` | `run` subparser with same args + top-level flags | Fully ported |
| `Command::Rebuild` | `rebuild` subparser | Fully ported |
| `Command::Export { out, pdf }` | `export` subparser with `--out` only (no `--pdf`) | **Enhancement** — Rust adds `--pdf` flag not in Python CLI |
| `Command::ConfigCheck` | `config-check` subparser | Fully ported |
| `MaintenanceCommand::Status` (`db-status`) | `maintenance db-status` | Fully ported |
| `MaintenanceCommand::Doctor { json }` (`db-doctor`) | `maintenance db-doctor` with `--json` | Fully ported |
| `MaintenanceCommand::Upgrade` (`db-upgrade`) | `maintenance db-upgrade` | Fully ported |
| `MaintenanceCommand::Reset { yes }` (`db-reset`) | `maintenance db-reset` with `--yes` | Fully ported |

**Note:** Python parser also has a top-level `--debug` flag and a `?` shorthand for `--help`. These are **not present in the Rust CLI**. The Rust `export` subcommand adds `--pdf` which is an enhancement rather than missing functionality.

## Config Loading & Validation (`cmd_config_check`, `database_file`)

Python reference: `forza/config.py::load_config()`, `forza/config.py::validate_config()`.

| Rust | Python | Status |
|------|--------|--------|
| `forza_config::load_config(path, strict=false)` returns `(AppConfig, Warnings)` | `load_config(path, strict=False)` returns `AppConfig` (warnings via logging) | **Partially ported** — Rust collects warnings explicitly as a Vec; Python logs them. Config struct fields and defaults are identical. |
| `forza_config::validate_config(&cfg)` returns `Result<(), Vec<String>>` | `validate_config(cfg)` raises `ConfigValidationError` with bullet-list message | **Partially ported** — Rust returns errors as a Vec; Python raises an exception. Validation rules (image_format, reasoning_mode, prompt active, workers >= 1, timeouts > 0, context_length > 0, eval_batch_size > 0, physical_batch_size > 0, reload_streak >= 1, max_width range, encode_quality range, temp_min < temp_max) are identical. |
| `database_file()` helper — falls back to `"data/forza.sqlite3"` on error | No equivalent fallback in Python (uses `cfg.database_file` directly) | Rust adds a safety fallback not present in Python. |

**Missing from Rust:** Python's `validate_config` also checks writable path parents (`_writable_path_checks`). The Rust version does **not** include these filesystem-writability checks — notable gap.

## Database Status (`cmd_db_status`)

Python reference: `forza/cli/maintenance.py::cmd_db_status()`.

| Rust | Python | Status |
|------|--------|--------|
| Uses `schema_status(db_path)` returning `SchemaStatus` enum | Uses `DatabaseService.status()` returning a rich `DbStatus` object with table counts, revision info, etc. | **Partially ported** — Rust only reports schema state (empty/current/incompatible). Python reports full database inventory: image_files, extraction_runs, lap_records, review_cases, export_artifacts, reference_tracks/cars, external_imports/laps, plus Alembic revisions. |

The Rust version is significantly simplified. It does not show table row counts or Alembic revision information.

## Database Doctor (`cmd_db_doctor`)

Python reference: `forza/cli/maintenance.py::cmd_db_doctor()`, `forza/application/db_doctor_service.py`.

| Rust | Python | Status |
|------|--------|--------|
| Uses `doctor::doctor_on_path(db_path)` returning a report with `checks: Vec<Check>` | Uses `DbDoctorService().run()` returning `DbDoctorReport` with checks having `severity`, `count`, `detail`, `ok` fields | **Partially ported** — Rust's check struct has `key`, `detail`, and an inferred severity (error if not ok). Python's checks have explicit `severity` field. The Rust JSON output maps severity to `"error"` for all non-ok checks, losing the granularity of Python's multi-severity system. |

The Rust version uses a simplified doctor from `forza-db::doctor`. It does not include the full battery of checks (foreign key violations, schema drift, review model error identity, etc.) that the Python `DbDoctorService` runs.

## Database Upgrade (`cmd_db_upgrade`)

Python reference: `forza/cli/maintenance.py::cmd_db_upgrade()`.

| Rust | Python | Status |
|------|--------|--------|
| Uses `upgrade(&db_path)` from `forza-db::migration` | Uses `upgrade_database(cfg.database_file)` + `seed_initial_reference_text_files()` | **Partially ported** — Rust's `upgrade` function handles schema creation/migration. Python additionally seeds reference text files (tracks/cars) after upgrade. The Rust code does not appear to seed references in the CLI path. |

## Database Reset (`cmd_db_reset`)

Python reference: `forza/cli/maintenance.py::cmd_db_reset()`, `_ensure_exclusive_access()`.

| Rust | Python | Status |
|------|--------|--------|
| Lists files to delete, requires `--yes` confirmation, deletes DB + WAL/SHM sidecars | Same logic plus `_ensure_exclusive_access()` which tries an EXCLUSIVE SQLite lock before deleting | **Partially ported** — Rust skips the exclusive-lock safety check. Python's `_ensure_exclusive_access` prevents deleting a database that another connection is actively using (audit finding C-2). Notable safety gap in the Rust version. |

## Dry Run (`cmd_run` with `dry_run=true`)

Python reference: `forza/cli/run.py::cmd_run()`, `forza/application/run_service.py::RunService.run()`.

| Rust | Python | Status |
|------|--------|--------|
| Loads config, opens DB connection, discovers images (or retries), prints plan without model calls | Uses `RunService().run()` with `DatabaseService` context manager, full discovery pipeline including preflight, extraction, rebuild | **Partially ported** — Rust implements a lightweight dry-run that only does image discovery and planning. Python's dry-run is embedded in the full `RunService.run()` flow which includes reference loading, run ID generation, database begin_run/complete_run lifecycle, etc. The Rust version skips the DB lifecycle management (begin/complete/fail run rows). |

## Live Run (`cmd_live_run`, called from `cmd_run` when not dry-run)

Python reference: `forza/cli/run.py::cmd_run()`, `forza/application/run_service.py::RunService.run()`.

| Rust | Python | Status |
|------|--------|--------|
| Uses `forza_app::spawn_extraction(params, control, event_handler)` with thread-based extraction and event-driven console output | Uses `RunService().run(cfg, refs, log, options=...)` which internally manages DB lifecycle, discovery, preflight, extraction batch, rebuild, metrics persistence | **Partially ported** — Rust delegates to `forza_app::spawn_extraction()` which handles the threaded extraction with events. Python uses a synchronous `RunService.run()` that manages everything in-process. The Rust version has explicit event handling (started, plan, image_started, image_done, progress, log, finished, failed) while Python uses logging + event emission internally. |

**Missing from Rust:** Python's run includes LM Studio preflight (`_preflight_lmstudio`), abandoned run reconciliation, runtime snapshot recording, and selection-based image file filtering. The Rust `cmd_live_run` does not appear to include these features (they may be handled inside `forza_app::spawn_extraction`, but the CLI layer doesn't expose them).

## Rebuild (`Command::Rebuild`)

Python reference: `forza/cli/rebuild.py::cmd_rebuild()`, `forza/application/rebuild_service.py::RebuildService.rebuild_outputs()`.

| Rust | Python | Status |
|------|--------|--------|
| Loads config, opens DB, calls `forza_app::services::rebuild::rebuild(&conn, &cfg.gamertag)`, prints outcome stats | Uses `DatabaseService` context manager, loads references, calls `RebuildService().rebuild_outputs(cfg, refs, log)` | **Partially ported** — Rust's rebuild is simplified: it directly calls the service with connection and gamertag. Python loads reference data first (`database.load_reference_data()`), passes cfg/refs/log to the service. The Rust version skips reference loading. |

## Export (`Command::Export`)

Python reference: `forza/cli/export.py::cmd_export()`, `forza/application/export_service.py::ExportService.clean_csv()`.

| Rust | Python | Status |
|------|--------|--------|
| Loads config, opens DB, calls `laps::list_clean_flat(&conn, &cfg.gamertag.to_lowercase())`, converts rows to `ExportRow`, exports CSV or PDF | Uses `ExportService().clean_csv(cfg, out)` which internally recompute_best_laps + list_clean_flat + csv export + artifact recording | **Partially ported** — Rust manually maps DB rows to `ExportRow` structs and handles both CSV and PDF output. Python's `ExportService.clean_csv()` also records the export artifact in the database (Rust does not). The Rust version adds a `--pdf` option that Python's CLI doesn't have (enhancement). |

**Missing from Rust:** Python's export service records an export artifact snapshot (`database.record_artifact(path=out_path, format="csv", run_id=run_id)`). Rust does not persist export artifacts.

## GUI Launch (`Command::Gui`)

Python reference: `forza/cli/gui.py::cmd_gui()`, `forza/gui/app.py` (not examined).

| Rust | Python | Status |
|------|--------|--------|
| Calls `forza_gui::run(&cli.config)` | Calls `run_gui(config_path=args.config, debug=args.debug)` and raises SystemExit with return code | **Partially ported** — Rust passes only the config path. Python also passes a `debug` flag (from CLI's top-level `--debug`). The Rust version does not support the `--debug` flag at all. |

## Key Functions/Types Exported by `main.rs`

The file exports **no public items** (it is a binary, not a library). Its internal functions are:

| Function | Purpose |
|----------|---------|
| `database_file()` | Resolve database path with fallback |
| `cmd_config_check()` | Validate and report config status |
| `cmd_db_status()` | Report schema state of SQLite DB |
| `cmd_db_doctor()` | Run DB integrity checks, output text/JSON |
| `cmd_db_reset()` | Delete DB + WAL/SHM files (with confirmation) |
| `cmd_run()` | Dry-run image discovery planning or delegate to live run |
| `cmd_live_run()` | Spawn threaded extraction with event-driven console output |
| `main()` | CLI entry point, dispatches subcommands |

## Summary Assessment

**Overall porting status: PARTIALLY PORTED**

The Rust CLI successfully ports the core command structure and argument parsing from Python. However, there are notable gaps:

1. **Missing `--debug` flag** — The Python CLI has a top-level `--debug` flag for logging control; the Rust version omits it entirely.
2. **Simplified DB status** — Rust only reports schema state (empty/current/incompatible), while Python shows full table row counts and Alembic revisions.
3. **Simplified DB doctor** — Rust uses a simplified check set without multi-severity grading or the full battery of integrity checks.
4. **Missing exclusive-lock safety on db-reset** — Python's `_ensure_exclusive_access()` prevents deleting an in-use database; Rust skips this.
5. **No reference data loading for rebuild/export** — Python loads references before rebuild/export operations; Rust does not.
6. **No export artifact recording** — Python records export artifacts in the DB; Rust does not.
7. **Config validation missing writable-path checks** — Python validates that output path parents are writable; Rust only validates config values.
8. **Dry-run skips DB lifecycle** — Python's dry-run goes through `RunService.run()` which manages begin/complete/fail run rows even in dry mode; Rust opens a connection but doesn't manage the full lifecycle.

The Rust CLI is functionally usable for its core commands (run, rebuild, export, config-check) but lacks some of the safety checks, diagnostic depth, and artifact persistence that the Python version provides.
