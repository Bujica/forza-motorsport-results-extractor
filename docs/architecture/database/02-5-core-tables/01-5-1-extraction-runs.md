# Database Architecture: 5. Core Tables: 5.1. `extraction_runs`

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: detailed shard split from `02-5-core-tables.md`
Last verified: 2026-06-15

Back to index: [`../02-5-core-tables.md`](../02-5-core-tables.md).

### 5.1. `extraction_runs`

One row per run lifecycle.

```sql
CREATE TABLE extraction_runs (
    id                           TEXT PRIMARY KEY,

    status                       TEXT NOT NULL DEFAULT 'pending',
    mode                         TEXT NOT NULL DEFAULT 'normal',
    -- persisted: normal | dry_run; run options are captured in config_extra_json

    backend                      TEXT NOT NULL DEFAULT 'lmstudio',
    model                        TEXT NOT NULL,

    prompt_snapshot_id            TEXT REFERENCES prompt_snapshots(id) ON DELETE RESTRICT,
    prompt_name                   TEXT,
    prompt_hash                   TEXT,

    input_dir                     TEXT,
    workers                       INTEGER NOT NULL DEFAULT 1,

    image_format                  TEXT,
    max_width                     INTEGER,
    encode_quality                INTEGER,
    grayscale                     INTEGER NOT NULL DEFAULT 0,

    context_length                INTEGER,
    reasoning_mode                TEXT,
    eval_batch_size               INTEGER,
    physical_batch_size           INTEGER,
    flash_attention               INTEGER,
    offload_kv_cache_to_gpu       INTEGER,
    max_completion_tokens         INTEGER,
    temperature                   REAL,
    max_retries                   INTEGER,

    timeout_connect               INTEGER,
    timeout_read                  INTEGER,
    performance_tps_floor         REAL,
    performance_reload_elapsed_s  REAL,
    performance_reload_streak     INTEGER,

    config_extra_json             TEXT,

    total_inputs                  INTEGER NOT NULL DEFAULT 0,
    to_process                    INTEGER NOT NULL DEFAULT 0,
    processed                     INTEGER NOT NULL DEFAULT 0,
    succeeded                     INTEGER NOT NULL DEFAULT 0,
    failed                        INTEGER NOT NULL DEFAULT 0,
    skipped                       INTEGER NOT NULL DEFAULT 0,
    duplicate_count               INTEGER NOT NULL DEFAULT 0,
    review_case_count             INTEGER NOT NULL DEFAULT 0,

    operational_error_code        TEXT,
    operational_error_message     TEXT,

    created_at                    TEXT NOT NULL,
    started_at                    TEXT,
    finished_at                   TEXT,

    CHECK (workers >= 1),
    CHECK (total_inputs >= 0),
    CHECK (to_process >= 0),
    CHECK (processed >= 0),
    CHECK (succeeded >= 0),
    CHECK (failed >= 0),
    CHECK (skipped >= 0),
    CHECK (duplicate_count >= 0)
);
```

Rules:

- `failed` on this table means run failure or failed result count depending on column context; `status='failed'` is operational lifecycle state.
- `operational_error_*` is for backend/preflight/config failures.
- A failed preflight must not create `extraction_results`; planned process
  inputs are reclassified to `decision='skip'`,
  `skip_reason='preflight_failed'`.
- Run counters are derived from persisted `run_inputs`, `extraction_results`,
  and `review_cases`, never from in-memory progress alone.
- Elapsed/rate measurements exclude time spent paused.
- Before a new run starts, any abandoned `running` run is reconciled to
  `status='failed'` with `operational_error_code='abandoned_run_recovered'`;
  each non-final result becomes `cancelled`.

### 5.2. `run_inputs`

Every file considered by a run.

```sql
CREATE TABLE run_inputs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,

    run_id                TEXT NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    image_file_id         TEXT REFERENCES image_files(id) ON DELETE SET NULL,

    input_order           INTEGER NOT NULL,
    input_path            TEXT NOT NULL,
    normalized_path       TEXT,
    file_name             TEXT,
    extension             TEXT,

    file_hash             TEXT,
    size_bytes            INTEGER,
    mtime_ns              INTEGER,

    decision              TEXT NOT NULL,
    -- process | skip | duplicate | missing | unsupported | outside_input | hash_failed

    process_reason        TEXT,
    -- full_run | force | retry_errors | manual

    skip_reason           TEXT,
    -- existing_ok | user_excluded | dry_run | rebuild_only |
    -- selection_excluded | preflight_failed

    duplicate_kind        TEXT,
    -- hash | batch

    duplicate_of_hash     TEXT,
    duplicate_of_input_id INTEGER REFERENCES run_inputs(id) ON DELETE SET NULL,

    created_at            TEXT NOT NULL,

    CHECK (input_order >= 0),
    CHECK (size_bytes IS NULL OR size_bytes >= 0)
);
```

Rules:

- `run_inputs` does not store `extraction_result_id`; the relationship is one-way through `extraction_results.run_input_id`.
- `decision='process'` requires `image_file_id`.
- `process_reason` may be `NULL` when it is simply the same as `extraction_runs.mode`.
- In retry-errors mode, the selected image uses `decision='process'` and `process_reason='retry_errors'`.
- Unsupported files, hash failures, missing retry targets, and retry targets
  outside the configured input directory use the specialized decisions
  `unsupported`, `hash_failed`, `missing`, and `outside_input`.
- A run limit still accounts for the complete considered input set; supported
  files outside the selected limit use `decision='skip'` and
  `skip_reason='selection_excluded'`.
- When a duplicate is detected inside the same run,
  `duplicate_of_input_id` points to the earlier canonical `run_inputs` row.

### 5.3. `image_files`

Observed physical image-file identity and current file state.

```sql
CREATE TABLE image_files (
    id                    TEXT PRIMARY KEY,

    file_hash             TEXT NOT NULL,
    size_bytes            INTEGER,

    width_px              INTEGER,
    height_px             INTEGER,
    bit_depth             INTEGER,
    color_mode            TEXT,
    mime_type             TEXT,
    image_format          TEXT,
    image_metadata_json   TEXT,

    current_name          TEXT,
    current_path          TEXT,
    semantic_name         TEXT,

    race_datetime         TEXT,
    race_date             TEXT,
    race_datetime_source  TEXT NOT NULL DEFAULT 'file_modified_at',

    file_status           TEXT NOT NULL DEFAULT 'available',
    -- available | missing

    best_lap_status       TEXT NOT NULL DEFAULT 'pending',
    -- pending | contributing | non_contributing

    first_seen_at         TEXT NOT NULL,
    last_seen_at          TEXT,
    missing_at            TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,

    CHECK (size_bytes IS NULL OR size_bytes >= 0),
    CHECK (width_px IS NULL OR width_px > 0),
    CHECK (height_px IS NULL OR height_px > 0)
);
```

Rules:

- This table must not store model, prompt, run, attempt, or lap semantics.
- `id` is the stable identity of one observed physical file.
- `file_hash` is content identity and is indexed, not unique. Duplicate
  physical files share a hash without collapsing into one row.
- `current_path` is the authoritative physical location when available and is
  exposed by runtime schemas as a string path.
- `current_name` is the operational source/display name.
- `semantic_name` is a suggested/presentation filename, not the operational
  identity.
- `image_metadata_json` stores raw JSON-safe decoder metadata for temporary
  retention and post-processing analysis only. It is not operational state and
  must not be queried as product behavior without first promoting the needed
  fields to explicit columns.
- The reset schema does not carry `original_name` or `original_path` as product
  state. First-seen path evidence belongs in `run_inputs` or audit history.
- `missing` means the file disappeared outside an explicit app delete action.
- Explicit GUI Delete removes the file row and related image database records;
  it is not retained as a file lifecycle status. Delete must reconcile duplicate
  parent pointers and active duplicate flags for the affected hash group.

### 5.4. `prompt_snapshots`

Immutable prompt evidence.

```sql
CREATE TABLE prompt_snapshots (
    id                    TEXT PRIMARY KEY,

    prompt_name           TEXT NOT NULL,
    version_label         TEXT,
    content_hash          TEXT NOT NULL,

    system_text           TEXT NOT NULL,
    user_text_template    TEXT,
    response_schema_json  TEXT,

    created_at            TEXT NOT NULL,

    UNIQUE(prompt_name, content_hash)
);
```

Rules:

- `id` is deterministic, not a UUID: `{prompt_name}:{content_hash}`.
- `content_hash` is a SHA-256 hash of the canonical prompt payload: `system_text`, `user_text_template`, and `response_schema_json` after stable JSON/text normalization.
- `prompt_name` is a stable descriptive label. The same prompt name may have multiple content hashes over time.
- `UNIQUE(prompt_name, content_hash)` prevents duplicate rows for the same named prompt version.
- Reusing an existing deterministic id must verify every persisted payload
  field; a mismatch is corruption and must fail instead of updating the row.
- Do not use `UNIQUE(prompt_name)`; it would block prompt history.
- Do not use `content_hash` alone as the primary key unless the project intentionally wants identical content under different prompt names to collapse into one row.

