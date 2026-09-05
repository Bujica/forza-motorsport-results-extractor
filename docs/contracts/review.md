# Review Contract

Implementation: Rust (forza-rust/) — current. Legacy Python (forza/) frozen at 0.21.0-beta.1.
Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: human review cases, correction flow, and model-error evidence
Last verified: 2026-09-05
Supersedes: review rules embedded in history and developer-guide sections
Related tests: unit tests in `forza-rust/crates/forza-db` (`repositories::reviews`, `corrections`, `flags`) and `forza-app` (`review_queue`, `rebuild`)

Review exists to detect likely model mistakes, let a human correct the
canonical database state, and preserve enough evidence to improve prompts,
models, and rules.

Review cases are the operator-facing surface for revisable findings. Internal
`image_flags` may support system state and integrity checks, but normal Images
and Image Details screens must not use raw flags as a substitute for Review
cases.

## Canonical Reasons

Review cases use exactly these semantic reasons:

```text
dirty_lap
track
weather
race_class
car
driver_name
```

Do not split field-family reasons into separate sub-reasons for every trigger.
The trigger explains why the case was suspicious; the reason identifies the
field family being reviewed. `driver_name` is the canonical reason for driver
identity/name problems, including empty names, numeric prefixes, invalid name
shape, or configured-player mismatch evidence.

System-generated Review flags use the same reason vocabulary. Adding a Review
reason requires updating the `REVIEW_FLAG_TYPES` list in
`forza-db/src/repositories/flags.rs`, the `LAP_SCOPED` / `IMAGE_SCOPED` lists
in `forza-db/src/repositories/reviews.rs`, the rusqlite `CHECK` constraints in
`forza-db/src/schema_ddl.rs`, and the DB Doctor vocabulary checks in the same
change.

Lap-scoped reasons (`dirty_lap`, `car`, `driver_name`) attach to one lap slot;
image-scoped reasons (`track`, `weather`, `race_class`) attach to the whole
image (see `LAP_SCOPED` / `IMAGE_SCOPED` in `reviews.rs` and the
image-scoped vs lap-scoped correction semantics in `corrections.rs`).

## Decision Contract

Operator decisions flow through `forza-app/src/services/review_queue.rs`
(`decide_case`, `ignore_case`, `reopen_case`) invoked by the worker's
`DecideCase` / `IgnoreCase` / `ReopenCase` requests. A `DecideCase` applies
the correction via
`repositories::corrections::apply_manual_correction` and then runs the full
`rebuild()` so derived state (frontier, candidates, flags) refreshes before
the UI reloads.

When a review decision corrects a model mistake
(`repositories::corrections::apply_manual_correction`):

- `review_cases.status` becomes `resolved`.
- `review_cases.outcome` becomes `confirmed`.
- `review_cases.decision_field` identifies the corrected field.
- `review_cases.model_value` stores the model value.
- `review_cases.corrected_value` stores the human-approved value.
- The correction is persisted in `review_corrections` under the stable key
  `{field}:{business_key}` (image-scoped fields store `lap_index` NULL).
- Canonical `lap_records` rows in scope are updated on the same path
  (image-scoped fields cover the whole image plus the case's linked lap).
- Raw model evidence remains reachable through the linked result/attempt/artifact
  chain.

There is no separate model-confirm action in the Rust GUI: confirming the
model means applying the current/model value through the same
`review-apply` → `DecideCase` path, which resolves the case with outcome
`confirmed` and keeps canonical rows consistent with the confirmed value.
(`model_error` remains a valid `outcome` vocabulary value for candidate and
legacy rows, but `apply_manual_correction` records `confirmed`.)

Ignoring a case is not a model confirmation. It records that the case should not
block the operator workflow.

## Case Status Vocabulary

Valid `review_cases.status` values and their meaning:

| Status | Set by | Meaning |
| --- | --- | --- |
| `open` | system | Case requires operator attention. |
| `resolved` | operator | Operator made an explicit decision (correct/confirm/ignore). |
| `ignored` | operator | Operator dismissed the case without a data correction. |
| `auto_resolved` | system | The condition that triggered the case no longer exists in the data (e.g. after a Rebuild or recompute that applied persisted corrections). No operator decision was recorded. |

`auto_resolved` is a system-set terminal state. It is functionally resolved: the
underlying data is consistent and no operator action is pending. GUI filter
surfaces must treat `auto_resolved` as belonging to the `resolved` bucket.
Filters that show `resolved` cases must also show `auto_resolved` cases. A
filter that matches only the literal string `"resolved"` and silently hides
`auto_resolved` is a bug.

## Correction Persistence Contract

Approved model-error corrections are persisted in `review_corrections` using
the stable key `{field}:{business_key}` (image file, field, and lap index
when the correction is lap-scoped). The stable key must not depend on
`lap_record_id`, because rebuild can delete and recreate canonical lap rows.

`rebuild()` must re-apply persisted corrections (`corrections::apply_all`)
before recalculating best laps, system review cases, and system flags.

## Display Contract

Review GUI screens must distinguish three values:

| Value | Source |
| --- | --- |
| Model value | `review_cases.model_value` or raw evidence. |
| Corrected value | `review_cases.corrected_value`. |
| Current canonical value | canonical domain row, usually `lap_records`. |

After resolution, the list and details must not show stale review snapshots as
if they were canonical state. A clean corrected lap must not display a dirty
marker in current-value fields.

## Identity Contract

Every review case must have a stable operator-facing identifier that remains
usable after sorting, filtering, and prioritization. A visual row number is not
enough for later investigation.

`review_cases.business_key` is the stable technical identifier. If the UI,
exports, logs, or reports expose a review identifier to the operator, that
identifier must be stable and either use `business_key` directly or be persisted
or derived from stable review identity. It must not be a transient visual row
number.

Current canonical lap-scoped Review keys use:

```text
<reason>:<image_file_id>:<lap_index>
```

for `dirty_lap`, `car`, and `driver_name`. Image-scoped keys use:

```text
<reason>:<image_file_id>
```

for `track`, `weather`, and `race_class`.

`driver_name` is lap-scoped because the corrected driver name belongs to one
extracted lap row. It must not depend on volatile `lap_record_id` values or
parsed lap milliseconds.

Refresh, upsert, and candidate detection use only the current canonical
`business_key` formats above. Legacy and semantic equivalents are not runtime
identity. They are repair-only evidence used by DB Doctor and internal
service-level repair tooling when present in old data. Current runtime Review
identity does not parse lap time to derive compatibility keys:

```text
<reason>:<image_file_id>:<lap_index>:<driver_normalized>
<reason>:<image_file_id>:<driver_normalized>:<car_normalized>:<best_lap_ms>
```

If legacy or semantic keys exist in a runtime database, DB Doctor must report
them before Review refresh results are treated as authoritative. Maintainers
one-time cleanup is still required. Normal Review code must not silently
preserve a second legacy identity system.

business keys. Archived rows must not collide with current candidate keys or act
as authority for future repair passes.

## Trigger Contract

Candidates are detected in `forza-db/src/repositories/reviews.rs`
(`query_review_candidates`, global over `lap_records`, not run-scoped) plus
the rain-time check in `repositories::laps`
(`append_rain_time_review_candidates`):

| Reason | Trigger | Condition |
| --- | --- | --- |
| `dirty_lap` | `model_marked_dirty` | lap is dirty AND on the best-lap frontier (dirty laps only matter for output) |
| `weather` | `weather_unknown` | weather is `unknown` (per image) |
| `weather` | `rain_time_suspicious` | best rain lap faster than best dry on the same track/class |
| `track` | `track_unknown` / `track_unresolved` / `track_not_in_reference` | empty/`Unknown`, ambiguous, or not in the reference catalog |
| `race_class` | `class_unknown` / `class_invalid` | `Unknown` or outside `E/D/C/B/A/TCR/S/R/P/X` |
| `car` | `car_empty` / `car_not_in_reference` | empty or not in the reference catalog |
| `driver_name` | `driver_name_empty` / `numeric_prefix` / `invalid_symbol` | via `forza-domain/src/review_rules.rs::driver_name_review_trigger` |

Cases are auto-created at the end of every run (the `rebuild()` derived
refresh in `extraction_runner.rs`) and by manual Rebuild
(`forza-app/src/services/rebuild.rs`: candidates → `upsert_review_cases`,
which preserves operator-resolved cases by business key and auto-resolves
cases whose condition no longer exists).

`driver_name` trigger `numeric_prefix` covers 1-3 leading digits separated from the
name by whitespace, underscore, hyphen, or period. Examples:

```text
42 LionZera7559
250 CyanoticBoot9
```

## Review-owned image flags

Open Review cases own one matching active system `image_flags` row, synced by
`repositories::flags::sync_review_flags` (called by `rebuild()`, by
`DecideCase`, by `IgnoreCase`, and by `ReopenCase` handling), so DB Doctor can
verify that review-visible problems and image-scoped evidence stay in sync.
The Review case is the user-facing product object; the flag row is supporting
infrastructure. Flag keys never embed volatile lap ids
(`lap:{img}:{type}:{idx}:{drv}:{trk}:{cls}` / `image:{img}:{type}`).

Vocabulary is enforced twice: rusqlite `CHECK` constraints in
`schema_ddl.rs` (`ck_review_cases_*_vocab`, `ck_image_flags_*_vocab`,
`ck_review_cases_trigger_vocab`) and DB Doctor checks
(`open_reviews_missing_active_flag`, `stale_active_review_flags`,
`review_corrections_invalid`, trigger-vocabulary checks).

Resolving, ignoring, or reopening a Review case synchronizes the matching system flag status. Users do not resolve or edit raw flags directly through the normal GUI. Corrections must flow through Review decisions so `review_cases`, `review_corrections`, `lap_records`, run counters, and flag evidence remain consistent.

Review reasons stay canonical and product-facing: `dirty_lap`, `track`, `weather`, `race_class`, `car`, and `driver_name`. Any more specific cause belongs in `trigger` or `error_type`, not in a separate raw flag UX.
