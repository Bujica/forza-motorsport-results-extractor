# Database Architecture: 5. Core Tables: 5.5. `model_runtime_snapshots`

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: detailed shard split from `02-5-core-tables.md`
Last verified: 2026-06-15

Back to index: [`../02-5-core-tables.md`](../02-5-core-tables.md).

### 5.5. `model_runtime_snapshots`

LM Studio runtime state observed by the app.

```sql
CREATE TABLE model_runtime_snapshots (
    id                          TEXT PRIMARY KEY,

    run_id                      TEXT NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    snapshot_kind               TEXT NOT NULL DEFAULT 'preflight',
    -- preflight | attempt_recheck | manual

    endpoint                    TEXT NOT NULL,
    configured_model            TEXT,
    matched_model               TEXT,
    loaded_model                TEXT,
    instance_id                 TEXT,

    display_name                TEXT,
    publisher                   TEXT,
    architecture                TEXT,
    format                      TEXT,
    params_string               TEXT,
    quantization                TEXT,
    selected_variant            TEXT,
    size_bytes                  INTEGER,
    max_context_length          INTEGER,
    capabilities_json           TEXT,

    desired_load_config_json    TEXT,
    effective_load_config_json  TEXT,
    load_time_seconds           REAL,

    health_ok                   INTEGER NOT NULL DEFAULT 0,
    health_message              TEXT,
    model_matches_config        INTEGER,

    captured_at                 TEXT NOT NULL,

    CHECK (size_bytes IS NULL OR size_bytes >= 0)
);

CREATE UNIQUE INDEX idx_runtime_one_preflight_per_run
ON model_runtime_snapshots(run_id)
WHERE snapshot_kind = 'preflight';
```

Rules:

- Capture a preflight snapshot before processing images.
- Capture a failed preflight snapshot when enough endpoint/runtime data is available.
- Mid-run reload/recheck snapshots are created through a callback supplied to the backend by the application layer.
- Each parallel worker records an `attempt_recheck` snapshot for the runtime it
  actually observes. An attempt points to that observed snapshot, including
  after a compatible worker reload or model instance/config change.

### 5.6. `extraction_results`

Final per-image extraction summary.

```sql
CREATE TABLE extraction_results (
    id                       TEXT PRIMARY KEY,

    run_id                   TEXT NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    run_input_id             INTEGER NOT NULL REFERENCES run_inputs(id) ON DELETE CASCADE,
    image_file_id            TEXT NOT NULL REFERENCES image_files(id) ON DELETE RESTRICT,

    status                   TEXT NOT NULL,
    -- pending | running | ok | error | cancelled

    error_type               TEXT,
    -- parse_error | validation_error | http_error | timeout |
    -- cancelled | all_attempts_failed | backend_error

    error_message            TEXT,

    accepted_attempt_id      TEXT REFERENCES extraction_attempts(id) ON DELETE RESTRICT,
    attempt_count            INTEGER NOT NULL DEFAULT 0,

    model                    TEXT,
    model_instance_id        TEXT,
    prompt_snapshot_id       TEXT REFERENCES prompt_snapshots(id) ON DELETE RESTRICT,

    input_tokens             INTEGER,
    output_tokens            INTEGER,
    reasoning_tokens         INTEGER,
    total_tokens             INTEGER,

    tokens_per_second        REAL,
    time_to_first_token_s    REAL,
    model_load_time_s        REAL,

    request_image_format     TEXT,
    request_image_mime_type  TEXT,
    request_image_width      INTEGER,
    request_image_height     INTEGER,
    request_image_bytes      INTEGER,

    duration_ms              INTEGER,

    created_at               TEXT NOT NULL,
    updated_at               TEXT,

    UNIQUE(run_id, image_file_id),
    UNIQUE(run_input_id),

    CHECK (attempt_count >= 0),
    CHECK (request_image_width IS NULL OR request_image_width > 0),
    CHECK (request_image_height IS NULL OR request_image_height > 0),
    CHECK (request_image_bytes IS NULL OR request_image_bytes >= 0)
);
```

Rules:

- `status='ok'` requires `accepted_attempt_id`.
- `accepted_attempt_id` points to the accepted attempt.
- Attempt-level payload/debug details stay in `extraction_attempts`.

### 5.7. `extraction_attempts`

One row per real `/chat` call.

```sql
CREATE TABLE extraction_attempts (
    id                         TEXT PRIMARY KEY,

    extraction_result_id        TEXT NOT NULL REFERENCES extraction_results(id) ON DELETE CASCADE,
    run_id                      TEXT NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    image_file_id               TEXT NOT NULL REFERENCES image_files(id) ON DELETE RESTRICT,
    runtime_snapshot_id         TEXT REFERENCES model_runtime_snapshots(id) ON DELETE SET NULL,

    attempt_number              INTEGER NOT NULL,
    attempt_reason              TEXT NOT NULL,
    -- initial | transport_retry | json_retry | semantic_retry | manual_retry

    status                      TEXT NOT NULL,
    -- ok | error | cancelled

    accepted                    INTEGER NOT NULL DEFAULT 0,
    rejected_reason             TEXT,
    -- transport_error | parse_error | semantic_validation | cancelled

    http_status                 INTEGER,
    error_code                  TEXT,
    error_message               TEXT,

    model                       TEXT,
    model_instance_id           TEXT,

    request_image_format        TEXT,
    request_image_mime_type     TEXT,
    request_image_width         INTEGER,
    request_image_height        INTEGER,
    request_image_bytes         INTEGER,

    context_length              INTEGER,
    reasoning_mode              TEXT,

    request_config_json         TEXT,
    request_messages_json       TEXT,
    request_hash                TEXT,
    retry_instruction_text      TEXT,

    raw_response                TEXT,
    parsed_json                 TEXT,
    parse_error                 TEXT,

    validation_status           TEXT,
    validation_issues_json      TEXT,

    response_stats_json         TEXT,
    model_load_config_json      TEXT,

    input_tokens                INTEGER,
    output_tokens               INTEGER,
    reasoning_tokens            INTEGER,
    total_tokens                INTEGER,

    time_to_first_token_s       REAL,
    duration_ms                 INTEGER,
    tokens_per_second           REAL,
    model_load_time_s           REAL,

    created_at                  TEXT NOT NULL,

    UNIQUE(extraction_result_id, attempt_number),
    CHECK (
        (accepted = 1 AND status = 'ok')
        OR
        (accepted = 0 AND status <> 'ok')
    ),
    CHECK (attempt_number >= 1),
    CHECK (request_image_width IS NULL OR request_image_width > 0),
    CHECK (request_image_height IS NULL OR request_image_height > 0),
    CHECK (request_image_bytes IS NULL OR request_image_bytes >= 0)
);

CREATE UNIQUE INDEX idx_attempts_one_accepted_per_result
ON extraction_attempts(extraction_result_id)
WHERE accepted = 1;
```

Rules:

- Store request messages with image data redacted.
- Do not persist base64 image payloads in SQLite.
- `request_hash` is SHA-256 over the canonical redacted request payload, not the original payload with base64.
- The canonical request payload includes `request_messages_json` as persisted, `request_config_json`, `prompt_snapshot_id`, `model`, image file `file_hash`, and request image metadata such as format, mime type, dimensions, and encoded byte count.
- The canonical hash input uses stable key ordering and UTF-8 bytes.
- Store raw response text for immediate GUI/debug access.
- Store canonical raw/debug files in `model_artifacts`.
- With the current pipeline contract, an attempt with `status='ok'` is always the accepted attempt for its result.
- To revoke acceptance in a future manual retry flow, update `accepted`, `status`, and `rejected_reason` in the same transaction or introduce a new status contract first.

### 5.8. `model_artifacts`

Integrity-tracked model/debug files.

```sql
CREATE TABLE model_artifacts (
    id                    TEXT PRIMARY KEY,

    run_id                TEXT NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    image_file_id         TEXT REFERENCES image_files(id) ON DELETE SET NULL,
    extraction_result_id  TEXT REFERENCES extraction_results(id) ON DELETE CASCADE,
    attempt_id            TEXT REFERENCES extraction_attempts(id) ON DELETE CASCADE,

    artifact_type         TEXT NOT NULL,
    -- raw_response | failed_attempt | request_preview |
    -- request_body_redacted | parsed_result | encoded_image | debug_json

    file_path             TEXT NOT NULL,
    relative_path         TEXT,

    sha256                TEXT NOT NULL,
    size_bytes            INTEGER NOT NULL CHECK(size_bytes >= 0),
    media_type            TEXT,

    is_canonical          INTEGER NOT NULL DEFAULT 0,

    created_at            TEXT NOT NULL
);
```

Rules:

- File artifacts require `sha256` and `size_bytes`.
- Accepted attempts should have either `raw_response` text or a canonical `raw_response` artifact, preferably both.
- Registering an already-known artifact path must verify its persisted hash,
  size, ownership, attempt link, and canonical flag. It must never rehash
  mutated content.
- `model_artifacts` and `export_artifacts` remain separate tables.

