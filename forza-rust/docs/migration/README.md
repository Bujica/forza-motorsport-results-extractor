# Rust Migration Analysis Index

## Overview

This directory contains detailed porting analysis reports for each crate in the `forza-rust` project. Each report documents what was ported from Python, what differs architecturally, and what remains deferred to future phases (Fase 7/8).

All reports follow a consistent format:
- **Status**: historical (superseded by migration_report.md)
- **Audience**: developer, maintainer, LLM
- **Scope**: specific crate analysis
- **Last verified**: 2026-08-27

## Crate Analysis Reports

| Report | Crate | Python Source | Porting Status | Key Notes |
|--------|-------|--------------|----------------|-----------|
| [forza-domain.md](./forza-domain.md) | `forza-rust/crates/forza-domain` | `forza/domain/` | **Fully ported** | Pure domain rules; zero filesystem/network access. Golden equivalence tests against Python-generated reference vectors. |
| [forza-config.md](./forza-config.md) | `forza-rust/crates/forza-config` | `forza/config.py`, `config_service.py` | **Fully ported** | INI config loading, validation, persistence. Only gap: path-writability checks omitted in validate_config. |
| [forza-db.md](./forza-db.md) | `forza-rust/crates/forza-db` | `forza/db/`, `gui_read/` | **Substantially ported** | SQLite schema, migrations, queries, repositories. Clean-break policy: Rust creates own databases from zero via DDL. Deferred to Fase 8: full image upsert, complex lap creation pipeline, rain-time review check, DB Doctor run-counter checks. |
| [forza-app.md](./forza-app.md) | `forza-rust/crates/forza-app` | `forza/application/`, `gui/controllers/` | **Substantially ported** | Application services: extraction, rebuild, settings, image inventory/debug/detail, review queue. Partial gaps: rebuild skips correction application step; extraction runner lacks multi-worker parallelism and abandoned run reconciliation. |
| [forza-cli.md](./forza-cli.md) | `forza-rust/crates/forza-cli` | `forza/cli/` | **Partially ported** | CLI interface using clap. Core commands (run, rebuild, export, config-check) functional. Gaps: missing --debug flag, simplified DB status/doctor, no exclusive-lock safety on db-reset, no reference data loading for rebuild/export, no export artifact recording. |
| [forza-gui.md](./forza-gui.md) | `forza-rust/crates/forza-gui` | `forza/gui/` | **Fully ported** | Slint GUI replacing PySide6 Qt. All 9 navigation pages, all signal/callback contracts. Architecture differs (mpsc channels + Tokio vs QThread/QtSignal) but functional behavior equivalent. Omissions: PDF generation, CSV export, external spreadsheet import, Records/Performance dashboard data. |
| [forza-lmstudio.md](./forza-lmstudio.md) | `forza-rust/crates/forza-lmstudio` | `forza/lmstudio/`, `pipeline/model_response.py` | **Substantially ported** | LM Studio HTTP client, backend extraction loop, response parsing/validation. Gaps: drops threading locks/cooperative cancellation/persistence hooks; flattens rich metadata structs into record fields; no context manager pattern. |
| [forza-output.md](./forza-output.md) | `forza-rust/crates/forza-output` | `forza/output/csv.py`, `pdf.py` | **Partially ported** | CSV export is complete byte-compatible port. PDF content planning fully ported; full ReportLab-style rendering unported (placeholder render_pdf produces valid but minimal text-based PDF). |
| [forza-pipeline.md](./forza-pipeline.md) | `forza-rust/crates/forza-pipeline` | `forza/pipeline/image.py` | **Substantially ported** | Image discovery, hashing, metadata, planning, encoding, naming. Gaps: log_duplicate_skips absent; timestamp fields deferred to callers; raw image info dict omitted from metadata inspection. |

## Architecture Differences (Rust vs Python)

| Aspect | Python | Rust |
|--------|--------|------|
| Database access | SQLAlchemy ORM + Alembic migrations | Raw SQL via rusqlite + r2d2_sqlite pool |
| GUI framework | PySide6 Qt + QThread/QtSignal | Slint + mpsc channels + Tokio runtime |
| HTTP client | synchronous requests.Session | async reqwest |
| Error handling | Python exceptions (ValueError, RuntimeError) | Rust typed enums via thiserror |
| Config parsing | configparser stdlib | Custom ordered INI reader/writer |
| Asset embedding | Runtime filesystem I/O | Compile-time include_str!() |
| Concurrency | ThreadPoolExecutor + threading.Event | tokio async + Arc<AtomicBool> |

## Migration Phases

- **Fase 6**: Pipeline crate (image discovery, hashing, encoding) — complete
- **Fase 7**: LM Studio integration (response parsing, backend extraction loop) — substantially complete
- **Fase 8**: Full application layer (extraction runner with parallel workers, abandoned run reconciliation, image upsert, complex lap creation, DB Doctor full checks) — deferred

## Key Design Decisions

1. **Clean-break policy** (database.md): Rust never opens Python-created databases in production; creates own from zero via DDL
2. **No ORM layer**: Raw SQL throughout instead of SQLAlchemy/SQLModel dependency inversion
3. **Scope-limited JSON repair**: Intentionally narrower than Python's full json_repair library because real malformed fixtures fail on validation, not syntax
4. **Compile-time asset embedding**: Reference data embedded at compile time via include_str!() instead of runtime filesystem I/O
5. **Typed enums with FromStr/Display**: Rust adds ergonomic improvements without altering domain logic or output values

## Related Files

- `migration_report.md` — High-level summary of all crates and overall porting status
- `forza-rust/crates/*/Cargo.toml` — Crate dependencies and build configuration
- `forza-rust/fixtures/expected/*` — Golden reference data for equivalence tests
- `docs/contracts/database.md`, `gui_signal_payloads.md`, `configuration.md` — Contract documents referenced by analysis reports
