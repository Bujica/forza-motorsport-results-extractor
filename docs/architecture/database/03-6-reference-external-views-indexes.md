# Database Architecture: 6. Reference, External, And Indexes

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: reference/external tables and index strategy
Last verified: 2026-06-15

Back to index: [`../database.md`](../database.md).

## 6. Reference, External, And Indexes

Reference/external tables:

```text
reference_tracks(id, name, normalized_name, aliases_json, active, created_at, updated_at)
reference_cars(id, name, normalized_name, race_class, aliases_json, active, created_at, updated_at)
external_record_imports(id, source_path, source_hash, status, active, totals, issues_json, timestamps)
external_lap_records(id, import_id, track, track_normalized, race_class, driver, driver_normalized, car, car_normalized, weather, best_lap, best_lap_ms, active, created_at)
```

## 7. Views

The active baseline does not define product views. GUI and DB Doctor reads use
repositories and read facades over indexed base tables, so view objects do not
become a parallel query contract.

## 8. Index Strategy

Do not create separate indexes for columns already covered by `UNIQUE` constraints. SQLite already creates backing B-trees for those constraints.

Create initially:

```sql
CREATE INDEX idx_image_files_hash
ON image_files(file_hash);

CREATE INDEX idx_image_files_status
ON image_files(file_status);

CREATE INDEX idx_image_files_best_lap_status
ON image_files(best_lap_status);

CREATE INDEX idx_run_inputs_run_decision
ON run_inputs(run_id, decision);

CREATE INDEX idx_run_inputs_process_reason
ON run_inputs(run_id, process_reason);

CREATE INDEX idx_run_inputs_image_file
ON run_inputs(image_file_id);

CREATE INDEX idx_run_inputs_hash
ON run_inputs(file_hash);

CREATE INDEX idx_extraction_runs_status
ON extraction_runs(status);

CREATE INDEX idx_extraction_runs_created
ON extraction_runs(created_at);

CREATE INDEX idx_extraction_results_status
ON extraction_results(status);

CREATE INDEX idx_extraction_results_image_file
ON extraction_results(image_file_id);

CREATE INDEX idx_attempts_run_status
ON extraction_attempts(run_id, status);

CREATE INDEX idx_attempts_reason
ON extraction_attempts(attempt_reason);

CREATE INDEX idx_lap_records_track_class_driver
ON lap_records(track_normalized, race_class, driver_normalized);

CREATE INDEX idx_lap_records_track_class_car
ON lap_records(track_normalized, race_class, car_normalized);

CREATE INDEX idx_lap_records_best_track_class_driver
ON lap_records(track_normalized, race_class, driver_normalized)
WHERE is_best_lap = 1;

CREATE INDEX idx_lap_records_best_track_class_car
ON lap_records(track_normalized, race_class, car_normalized)
WHERE is_best_lap = 1;

CREATE INDEX idx_lap_records_best_gui_order
ON lap_records(track, race_class, weather, best_lap_ms, driver, car)
WHERE is_best_lap = 1;

CREATE INDEX idx_lap_records_image_file
ON lap_records(image_file_id);

CREATE INDEX idx_external_lap_records_active_order
ON external_lap_records(track, race_class, best_lap_ms)
WHERE active = 1;

CREATE INDEX idx_model_artifacts_run_image_file
ON model_artifacts(run_id, image_file_id);

CREATE INDEX idx_model_artifacts_attempt
ON model_artifacts(attempt_id);

CREATE INDEX idx_model_runtime_run_kind
ON model_runtime_snapshots(run_id, snapshot_kind);

CREATE INDEX idx_review_cases_status_reason
ON review_cases(status, reason);

CREATE INDEX idx_image_flags_file_type_status
ON image_flags(image_file_id, flag_type, status);
```

Do not index initially:

```text
request image byte/width/height fields
duration_ms
http_status
tokens_per_second
time_to_first_token_s
best_lap
best_lap_ms alone
attempt created_at
lap created_at
most image_files image metadata fields
pure boolean fields without a partial predicate
```

## 9. Consistency Invariants

The quiescent or reconciled vNext database is valid only when these conditions
hold. A currently active run may temporarily have running results, incomplete
counters, and process inputs whose result shell has not been created yet:

```text
1. Every run has a run status; run status never uses ok/error.
2. Preflight failure creates no extraction_results.
3. Every considered input has a run_inputs row.
4. Every run_input with decision=process has image_file_id set.
5. Every run_input with decision=process has exactly one extraction_result.
6. Every ok extraction_result has accepted_attempt_id.
7. accepted_attempt_id points to an accepted attempt.
8. A partial unique index prevents more than one accepted attempt per result.
9. No error extraction_result has lap_records.
10. Retry does not duplicate lap_records.
11. Rebuild is idempotent.
12. lap_records.is_best_lap can be rebuilt from lap_records alone.
13. Every accepted attempt has raw response text or a canonical raw artifact.
14. Every canonical raw artifact validates sha256 and size_bytes against disk.
15. prompt_snapshot_id points to immutable prompt content whose deterministic id
    and content_hash recompute from the persisted payload; run prompt_name/hash
    match the linked snapshot.
16. Every run past preflight has one preflight runtime snapshot.
17. No new runtime screen reads legacy JSON/cache as canonical state.
18. run_inputs.decision and process_reason are never overloaded.
19. Request payload stored in DB is redacted and does not contain image base64.
20. review_cases.business_key never depends on lap_record_id.
21. image_flags.flag_key prevents duplicate image-level and lap-level flags.
22. image_flags.flag_key never depends on lap_record_id.
23. request_hash is computed from the same redacted payload that is stored in SQLite.
24. A final run has no pending/running extraction results.
25. Every real attempt is append-only and retains its runtime snapshot and artifact evidence.
26. Every failed attempt has a registered failed_attempt artifact.
27. Run counters equal the relational rows from which they are derived.
28. Export artifacts validate sha256 and size_bytes against immutable
    content-addressed files; an existing snapshot with divergent bytes is rejected.
29. Effective SQLite columns and server defaults match the frozen migration contract.
30. Starting a new run reconciles abandoned running runs before creating new work.
31. SQLite integrity_check reports ok and foreign_key_check reports no violations.
32. Every registered model artifact validates sha256 and size_bytes against disk;
    registering an existing path with divergent content or ownership is rejected.
```

## 10. Runtime Snapshot Capture Contract

`lmstudio/backend.py` must not import or call database services directly.

For runtime snapshots after reload/recheck, use a callback injected by the application layer:

```python
def on_runtime_snapshot(snapshot) -> str:
    """Persist the snapshot and return model_runtime_snapshots.id."""
```

The backend can call this callback when it observes or changes runtime state. `ExtractionService` or `RunService` owns the persistence. Attempts then store the returned `runtime_snapshot_id`.

This is more precise than post-hoc reconstruction and less indirect than a generic event bus.

