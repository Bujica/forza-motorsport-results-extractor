# Contract Translation Catalog (Python static tests → Rust)

Status: current
Audience: developer, LLM
Lifecycle: permanent
Scope: mapping of the executable contract guards to their Rust translation targets
Last verified: 2026-08-25

The Python `tests/*_static.py` suite guards contracts by inspection. The Rust
port does not copy the textual-inspection technique; it must preserve the
contract each guard protects, expressed as unit/integration tests against real
types. This catalog is the checklist for that translation
(migration plan Fase 0/7.5). Files marked "Python-only" have no Rust
equivalent because the surface itself disappears with Qt/SQLModel.

Legend: target crate — `domain`, `config`, `db`, `pipeline`, `lmstudio`,
`app`, `output`, `cli`, `gui`.

## Identity and packaging

| Python guard | Target | Rust contract |
| --- | --- | --- |
| `app_info` | cli/gui | App identity constants exist and match product naming; `--version` wired. |
| `beta_packaging` | output | Bundle artifact name pattern + one-folder policy documentation exists. |
| `product_identity` | cli/gui | README/product strings consistent. |
| `open_source_readiness` | — (repo policy) | Keep as repo check, not runtime code. |

## Database schema and integrity

| Python guard | Target | Rust contract |
| --- | --- | --- |
| `vocabulary_check_constraints` | db | Every CHECK vocabulary boundary from `forza-rust/docs/database.md`. |
| `db_entities_facade` | db | Entity module re-exports stable. |
| `orm_aliases` | — (SQLModel detail) | No direct translation; column names covered by schema tests. |
| `image_file_domain_status_enums` | domain/db | File/best-lap status enums with explicit persisted representation. |
| `image_file_promoted_fields` | db | Image row carries promoted identity fields used by GUI reads. |
| `lap_record_source_file_column` | db | `source_file` persisted on lap rows. |
| `model_extraction_attempt_status_enum` | db/domain | Attempt status enum values `ok/error/cancelled` + acceptance rule. |
| `review_case_number_column` / `_unique` | db | Case numbering contiguous-able and unique. |
| `review_case_domain_enum_fields` / `_reason_trigger_constraints` | db | Review vocabularies enforced at insert/update. |
| `review_correction_constraints` | db | Correction field/cause vocabularies + stable_key uniqueness. |
| `review_case_dead_fields` | db | Removed columns stay removed. |
| `review_case_display_fields_column` | db | Display snapshot fields persist for queue rendering. |
| `community_records_sql_authority` | db | External records read from SQL only. |
| `reference_sql_authority` | db | Reference tracks/cars seeded in SQL; assets are seed source. |
| `raw_response_record` | lmstudio/db | Raw response + parsed evidence persisted per attempt. |
| `extraction_result_model_response_stats` | db | Response stats fields persisted on results. |
| `extraction_run_domain_canonical_names` | domain/db | Canonical track/class normalization persisted. |
| `images_first_schema_contract_docs` | db | Schema docs stay aligned with migrations. |
| `lap_row_like_ordering` | db/output | Lap ordering rule (index, time) preserved in reads/exports. |
| `external_record_import_totals_columns` | db | Import totals counters persisted and checked. |

## DB doctor

| Python guard | Target | Rust contract |
| --- | --- | --- |
| `db_doctor_sqlite_checks` | db | Integrity/foreign-key checks report structured findings. |
| `db_doctor_schema_checks` | db | Column-level drift detection incl. quoted identifiers. |
| `db_doctor_run_checks` / `_status_checks` | db | Run counter reconciliation rules. |
| `db_doctor_review_checks` | db | Review integrity checks (canonical keys, duplicates). |
| `db_doctor_image_file_checks` | db | Image lifecycle/duplicate-group checks. |
| `db_doctor_modular_contracts` | app/db | Doctor registry stays modular per area. |

## Session/threading and run lifecycle

| Python guard | Target | Rust contract |
| --- | --- | --- |
| `db_session_provider_thread_safety` | db/app | Engine init/close under lock → pool initialization is thread-safe. |
| `run_service_event_backend` | app | RunService emits typed events to a backend sink. |
| `controller_event_type_matching` | gui/app | Event types consumed match emitted set. |
| `extraction_service_event` | app | ExtractionService emits progress/result events. |
| `run_lifecycle_reconcile_abandoned` | app | Abandoned running runs reconciled on startup; one corrupt run doesn't block others. |

## Pipeline and images

| Python guard | Target | Rust contract |
| --- | --- | --- |
| `image_inventory_scan_missing_candidates` | pipeline/app | Scan reconciliation marks missing files without walking unrelated rows. |
| `image_processing_status_projection` | db/app | Processing status derived from latest result per image. |
| `line_loading_helper` | domain | Shared line-list loader behavior. |

## LLM backend

| Python guard | Target | Rust contract |
| --- | --- | --- |
| `llm_backend_model_result_contract` | lmstudio | Backend returns typed extraction results; errors classified. |

## Rebuild

| Python guard | Target | Rust contract |
| --- | --- | --- |
| `rebuild` | app | Rebuild regenerates derived state globally, preserves review-authored data, emits event. |

## GUI contracts

The Qt implementation disappears; the *operator-facing* contracts survive in
Slint form: same sections, filters, states, callback semantics, worker
boundaries, signal payload shapes.

| Python guard group | Target | Surviving contract |
| --- | --- | --- |
| `gui_read_*` (9 files) | app/gui | Read facade returns typed rows for images/laps/review/run/dashboard/artifact/debug/context; session provider reuse. |
| `gui_write_location`, `gui_settings_write`, `gui_settings`, `gui_config_view_refresh` | gui/app | Writes go through write service; settings save triggers config reload + best-lap recompute signal. |
| `gui_image_management`, `gui_image_inventory_worker`, `gui_image_status_projection`, `gui_process`, `gui_process_screen` | gui | Image browser actions (rescan/rename/export/delete), background refresh worker, Run All + elapsed status. |
| `gui_review_screen`, `review_controller` | gui/app | Review queue buckets incl. `auto_resolved` under Resolved; decisions via write service; candidate ordering deterministic. |
| `gui_best_laps` | gui/output | Table + top summary; filtered exports; gamertag filter. |
| `gui_performance` | app/gui | Performance dashboard reads through service + worker. |
| `gui_evaluation_tools`, `gui_image_debug`, `gui_image_detail`, `image_detail_debug_deeplink`, `image_detail_debug_navigation` | gui | Diagnostics surfaces: image debug tabs, detail navigation, debug deeplink. |
| `gui_signal_object_payload_docs`, `gui_service_level_contract` | gui/app | Event/payload shapes documented and stable; controllers stay read/write-facade clients. |

## Docs/process guards (meta)

| Python guard | Target |
| --- | --- |
| `docs_maintainability` | Repo check: active-doc line limits, no Lab residue. Keep as CI script/test over docs. |
| `removed_clean_break_surfaces` | Guard that removed surfaces stay removed; translate as absence checks where meaningful (e.g., no legacy CLI commands). |
| `public_docs_onboarding` | Public docs contain required tokens; keep as doc test. |

## Coverage note

Every non-"Python-only" row above must map to at least one Rust test before its
phase's conclusion criterion is met. The migration plan's §7.5 governs.
