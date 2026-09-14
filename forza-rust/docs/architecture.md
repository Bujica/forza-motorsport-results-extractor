# Architecture

Status: current
Audience: developer, maintainer, LLM
Scope: crate layout, dependency direction, runtime flows.

## Crates (`forza-rust/crates/`)

| Crate | Role |
| --- | --- |
| `forza-domain` | Pure rules: lap parsing, frontier, review triggers, normalizers, ordering, reference data. No I/O. Leaf dependency. |
| `forza-config` | `forza_config.ini` parsing (`load_config`), validation (`validate_config`), atomic save with backup. |
| `forza-db` | rusqlite storage: `schema_ddl.rs` (frozen DDL, `SCHEMA_VERSION = 2`), `migration.rs` (`upgrade()` builds from zero), repositories, `ids.rs` (typed row identities), `gui_queries.rs`, `image_debug.rs`, `doctor/` (~70 checks in submodules). |
| `forza-pipeline` | Discovery, planning/dedup, hashing, metadata, encoding, naming. No DB. |
| `forza-lmstudio` | Async HTTP backend (`backend.rs`), model client (`client.rs`), load-config compat, response parse/validate/repair. |
| `forza-output` | CSV (BOM + CRLF) and dependency-free PDF writer (cover, indexed TOC with section links, class tables, archive-before-write). |
| `forza-app` | Services orchestrating the above: extraction runner, replay, rebuild, review queue, inventory, settings, import, debug. |
| `forza-cli` | Thin clap adapters over `forza-app` (`commands/` modules; `main.rs` only parses + dispatches). |
| `forza-gui` | Slint UI + worker threads (see `gui.md`). Does not depend on `forza-lmstudio`. |

Dependency direction: `domain`/`pipeline` are leaves (third-party deps only);
`app` orchestrates; `cli`/`gui` are thin over `app`. Do not introduce cycles
or let runtime crates grow Python-style service layers. Shared third-party
versions are inherited from `[workspace.dependencies]` (see
`development.md`); race classes are owned by `RaceClass`
(`forza-domain/src/race_class.rs`: order, color, CSV parsing — never match
class strings ad hoc).

## Extraction run flow (`forza-app/src/services/extraction_runner.rs`)

1. `reconcile_abandoned_runs` (recovers `running` + stale `pending` runs).
2. Discovery + `plan_images` (new / cached-duplicate / batch-duplicate / existing / skipped).
3. Run row (`pending` → `running`), prompt snapshot, run metadata, preflight
   runtime snapshot.
4. Skip/duplicate inputs recorded with full evidence (`duplicate_kind`,
   hashes, batch links).
5. Sequential path, or multi-worker path (`workers > 1`): inputs/results are
   **pre-allocated on the main connection** - workers never compute ids or
   `input_order` (see code comments for why). Model calls take permits from
   a run-shared semaphore (`inference_concurrency`, capped at workers);
   everything else stays parallel.
6. Per image: upsert image row → pending result → encode → `ensure_loaded` →
   extract with attempt persistence → derive laps → finalize (`ok`/`error`;
   never left `running`). Every failure logs `error_type: message` and lands
   in retryable `error_type`/`error_message` columns.
7. `complete_run` (counters recomputed from relational rows) → `rebuild()`
   (corrections, best laps, review cases + system flags, per-run counts).

Cancelled runs exit the CLI with code 130.

## Review/flag lifecycle

Every run end (and manual Rebuild) refreshes review cases from lap rows and
syncs one active system flag per open case (`sync_review_flags`). Operator
decide/reopen resolve cases and re-sync flags. Details in `reviews.md`.

## GUI threading (`forza-gui/src/worker.rs`)

Fixed 4-worker pool sharing one mpsc queue; pooled r2d2 connections;
responses marshal via `slint::invoke_from_event_loop`. See `gui.md`.
