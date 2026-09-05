Implementation: Rust (forza-rust/) — current. Legacy Python (forza/) frozen at 0.21.0-beta.1.

# Architecture Overview

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: system-level structure and source-of-truth overview
Last verified: 2026-09-05
Supersedes: high-level architecture notes scattered across developer guide
Related tests: `cargo test --workspace` (run in `forza-rust/`)

Forza Screenshot Extractor is a desktop-first application that processes Forza
Motorsport race-result screenshots with a local LM Studio vision model, stores
runtime state in SQLite, supports human review, and exports best-lap records.

The two binaries are `forza.exe` (CLI, clap arg parsing) and `forza-gui.exe`
(Slint UI), built via `cargo build -p forza-cli -p forza-gui` in `forza-rust/`.
Build identity is workspace `Cargo.toml` version `0.1.0`, surfaced as
`forza-app::APP_VERSION` (`forza.exe --version`, GUI title, every run row).

## Primary Flow

```text
data/input images
  -> image inventory
  -> extraction run
  -> LM Studio attempts
  -> raw artifacts and parsed results
  -> lap_records
  -> review cases and image flags
  -> rebuild/recompute
  -> best-lap views and exports
```

## Crate Roles

| Crate | Role |
| --- | --- |
| `forza-app` | Orchestration services for runs, rebuild, images, DB Doctor, export, and config. |
| `forza-db` | rusqlite persistence: schema DDL, `migration::upgrade()`, repositories, and SQLite connection helpers. |
| `forza-gui` | Slint UI: pages, callbacks/state, worker threads, and GUI read/write services. |
| `forza-lmstudio` | Native LM Studio REST API boundary (reqwest+tokio HTTP backend). |
| `forza-pipeline` | Image processing and extraction orchestration helpers (discovery/planning/hashing/metadata/encoding/naming). |
| `forza-domain` | Domain rules independent of UI and persistence (lap/frontier/review_rules/normalizer/ordering/race_class). |
| `forza-output` | Export and report generation (CSV BOM+CRLF, dependency-free PDF writer with TOC links). |
| `forza-config` | `forza_config.ini` loading (`load_config`) and validation (`validate_config`). |
| `forza-cli` | Thin clap command adapters delegating to `forza-app` services. |

## Authority Order

When sources disagree:

1. Contracts in `docs/contracts/` define intended behavior.
2. Architecture in `docs/architecture/` explains structure.
3. `docs/project_status.md` identifies known issues.
4. History explains how the project reached the current state.
