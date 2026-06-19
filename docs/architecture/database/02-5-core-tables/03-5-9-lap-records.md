# Database Architecture: 5. Core Tables: 5.9. `lap_records`

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: detailed shard split from `02-5-core-tables.md`
Last verified: 2026-06-15

Back to index: [`../02-5-core-tables.md`](../02-5-core-tables.md).

### 5.9. `lap_records`

Accepted normalized lap rows.

```sql
CREATE TABLE lap_records (
    id                    TEXT PRIMARY KEY,

    run_id                TEXT NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    image_file_id         TEXT NOT NULL REFERENCES image_files(id) ON DELETE RESTRICT,
    extraction_result_id  TEXT NOT NULL REFERENCES extraction_results(id) ON DELETE CASCADE,

    lap_index             INTEGER NOT NULL,

    driver                TEXT NOT NULL DEFAULT '',
    driver_normalized     TEXT NOT NULL DEFAULT '',

    car                   TEXT NOT NULL DEFAULT '',
    car_normalized        TEXT NOT NULL DEFAULT '',

    race_class            TEXT NOT NULL DEFAULT '',
    track                 TEXT NOT NULL DEFAULT '',
    track_normalized      TEXT NOT NULL DEFAULT '',

    weather               TEXT NOT NULL DEFAULT 'unknown',
    temp_f                REAL,
    temp_c                REAL,

    best_lap              TEXT NOT NULL DEFAULT '',
    best_lap_ms           INTEGER NOT NULL,

    dirty                 INTEGER NOT NULL DEFAULT 0,

    raw_lap_json          TEXT,

    is_best_lap           INTEGER NOT NULL DEFAULT 0,

    created_at            TEXT NOT NULL,

    UNIQUE(extraction_result_id, lap_index),
    UNIQUE(image_file_id, run_id, lap_index),

    CHECK (lap_index >= 0),
    CHECK (best_lap_ms >= 0)
);
```

Rules:

- Do not use `NULL` for `driver` or `car`; use empty strings for unknown values.
- `best_lap_ms` is the canonical comparison value.
- `best_lap` is display text.
- `is_best_lap` is derived and rebuilt after the run.
- Do not add a `confidence` field until the pipeline actually computes confidence.

### 5.10. `review_cases`

Human review state and model-error audit trail. Raw model output still belongs
to `extraction_attempts` and `model_artifacts`; `review_cases` stores why a
field was suspicious, what the operator decided, and whether the model was
confirmed or corrected.

```sql
CREATE TABLE review_cases (
    id                    TEXT PRIMARY KEY,

    run_id                TEXT REFERENCES extraction_runs(id) ON DELETE SET NULL,
    image_file_id         TEXT REFERENCES image_files(id) ON DELETE RESTRICT,
    extraction_result_id  TEXT REFERENCES extraction_results(id) ON DELETE SET NULL,
    lap_record_id         TEXT REFERENCES lap_records(id) ON DELETE SET NULL,

    status                TEXT NOT NULL DEFAULT 'open',
    -- open | resolved | ignored | auto_resolved

    reason                TEXT NOT NULL,
    -- dirty_lap | track | weather | race_class | car | gamertag | driver_name

    trigger               TEXT,
    -- Deterministic suspicion source, for example track_unresolved,
    -- weather_unknown, numeric_prefix, car_not_in_reference.

    outcome               TEXT NOT NULL DEFAULT 'pending',
    -- pending | confirmed | model_error | ignored

    decision_field        TEXT,
    model_value           TEXT,
    corrected_value       TEXT,
    error_type            TEXT,

    severity              TEXT NOT NULL DEFAULT 'warning',
    -- info | warning | error

    business_key          TEXT NOT NULL UNIQUE,

    driver                TEXT,
    driver_normalized     TEXT,
    track                 TEXT,
    track_normalized      TEXT,
    race_class            TEXT,
    car                   TEXT,
    car_normalized        TEXT,
    lap_index             INTEGER,
    best_lap              TEXT,

    message               TEXT,
    suggestions_json      TEXT,

    created_at            TEXT NOT NULL,
    updated_at            TEXT,
    resolved_at           TEXT,
    resolution_note       TEXT
);
```

Canonical `business_key` formats:

```text
image-level: {reason}:{image_file_id}
lap-level:   {reason}:{image_file_id}:{lap_index}
```

Rules:

- `business_key` never depends on `lap_record_id`.
- All nullable key parts are serialized as empty strings.
- `reason` is one of the canonical review reasons: `dirty_lap`, `track`,
  `weather`, `race_class`, `car`, `driver_name`, or `driver_name`.
  Do not create separate reasons for `track_unknown`, `track_unresolved`,
  `weather_unknown`, `car_not_in_reference`, or `rain_time_suspicious`; store
  those as `trigger`.
- DB Doctor's `review_cases_invalid_reason` check must stay aligned with the
  `ck_review_cases_reason_vocab` constraint.
- `outcome='model_error'` means the operator corrected a model value and the
  row is eligible for improvement workflows and regression samples.
- `outcome='confirmed'` means the suspicious value was reviewed and kept.
- Corrected reviews must keep `model_value`, `corrected_value`, and
  `decision_field` so resolved cases remain auditable.
- Dirty-lap corrections store canonical clean lap times without dirty markers
  in `lap_records.best_lap`; dirty markers are rendered from `lap_records.dirty`.
- Legacy and semantic Review key equivalents are repair-only evidence. Normal
  runtime refresh/upsert uses the canonical formats above.

### 5.11. `review_corrections`

Durable operator-approved model-error corrections. This table exists so rebuild
can recreate volatile `lap_records` and still re-apply human corrections before
derived state is recalculated.

```sql
CREATE TABLE review_corrections (
    id                    TEXT PRIMARY KEY,
    stable_key            TEXT NOT NULL UNIQUE,
    image_file_id         TEXT NOT NULL REFERENCES image_files(id) ON DELETE RESTRICT,
    lap_index             INTEGER,
    field                 TEXT NOT NULL,
    model_value           TEXT,
    corrected_value       TEXT NOT NULL,
    error_type            TEXT,
    cause                 TEXT NOT NULL DEFAULT 'unknown',
    review_case_id        TEXT REFERENCES review_cases(id) ON DELETE SET NULL,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);
```

Rules:

- `stable_key` is based on `image_file_id`, `field`, and `lap_index` for
  lap-scoped corrections.
- `stable_key` must not depend on `lap_record_id`.
- Rebuild applies `review_corrections` after recreating accepted lap rows and
  before recalculating best laps, system review cases, and system flags.
- `review_case_id` is audit linkage only. Losing it must not prevent the stable
  correction from being re-applied.

### 5.12. `image_flags`

Image/lap flags for difficult images, uncertainty, and user/system state.

```sql
CREATE TABLE image_flags (
    id                    TEXT PRIMARY KEY,

    image_file_id         TEXT NOT NULL REFERENCES image_files(id) ON DELETE RESTRICT,
    run_id                TEXT REFERENCES extraction_runs(id) ON DELETE SET NULL,
    extraction_result_id  TEXT REFERENCES extraction_results(id) ON DELETE SET NULL,
    lap_record_id         TEXT REFERENCES lap_records(id) ON DELETE SET NULL,

    flag_key              TEXT NOT NULL UNIQUE,
    flag_scope            TEXT NOT NULL DEFAULT 'image',
    -- image | lap

    lap_index             INTEGER,
    driver_normalized     TEXT,
    track_normalized      TEXT,
    race_class            TEXT,

    flag_type             TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'active',
    -- active | resolved | ignored

    created_by            TEXT NOT NULL DEFAULT 'system',
    -- system | user

    reason                TEXT,
    note                  TEXT,

    created_at            TEXT NOT NULL,
    resolved_at           TEXT
);
```

Canonical `flag_key` format:

```text
image-level: image:{image_file_id}:{flag_type}
lap-level:   lap:{image_file_id}:{flag_type}:{lap_index}:{driver_normalized}:{track_normalized}:{race_class}
```

Rules:

- Use `flag_key` instead of a nullable-column `UNIQUE(image_file_id, flag_type, lap_record_id)`.
- This avoids SQLite's `NULL` uniqueness behavior.
- `flag_key` never uses `lap_record_id`; the lap primary key is an optional pointer, not identity.
- All nullable key parts are serialized as empty strings.

### 5.13. `export_artifacts`

User-facing generated outputs.

```sql
CREATE TABLE export_artifacts (
    id                    TEXT PRIMARY KEY,
    run_id                TEXT REFERENCES extraction_runs(id) ON DELETE SET NULL,

    artifact_type         TEXT NOT NULL,
    -- pdf | csv | review_package | lab_report

    file_path             TEXT NOT NULL,
    relative_path         TEXT,
    sha256                TEXT,
    size_bytes            INTEGER,
    created_at            TEXT NOT NULL,

    CHECK (size_bytes IS NULL OR size_bytes >= 0)
);
```

### 5.14. Foreign Key Delete Policy

SQLite defaults to `RESTRICT`, so every important parent-child relationship must be explicit.

Use these rules:

- Run-owned execution evidence uses `ON DELETE CASCADE` from `extraction_runs`: `run_inputs`, `model_runtime_snapshots`, `extraction_results`, `extraction_attempts`, `model_artifacts`, and `lap_records`.
- Result-owned evidence uses `ON DELETE CASCADE` from `extraction_results`: `extraction_attempts`, `model_artifacts`, and `lap_records`.
- Stable image files use `file_status` for `available`/`missing` inventory
  state. Explicit GUI Delete removes the selected image asset through the
  write service, which first removes related image-scoped rows in a controlled
  order.
- Required links to `image_files` use `ON DELETE RESTRICT` so accidental parent
  deletion cannot silently cascade evidence.
- Optional links from review/debug state use `ON DELETE SET NULL`.
- `review_cases.lap_record_id` and `image_flags.lap_record_id` use `ON DELETE SET NULL`, because rebuild can delete and recreate `lap_records`.
- Business keys and flag keys must not depend on volatile row IDs from derived tables.
- Rebuild code should still delete/reinsert derived rows in a clear order; FK actions are the safety net, not a substitute for intentional rebuild transactions.

