# Review Contract

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: human review cases, correction flow, and model-error evidence
Last verified: 2026-06-15
Supersedes: review rules embedded in history and developer-guide sections
Related tests: `tests/test_gui_write_dirty_decisions.py`, `tests/test_gui_write_field_decisions.py`, `tests/test_review_controller_static.py`, `tests/test_raw_response_and_review_linkage.py`

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
reason requires updating `image_flags.flag_type` in the Python enum, SQLModel
constraint, clean baseline SQL, and DB Doctor vocabulary checks in the same
change.

## Decision Contract

When a review decision corrects a model mistake:

- `review_cases.status` becomes `resolved`.
- `review_cases.outcome` becomes `model_error`.
- `review_cases.decision_field` identifies the corrected field.
- `review_cases.model_value` stores the model value.
- `review_cases.corrected_value` stores the human-approved value.
- `review_cases.error_type` stores a stable error category.
- Canonical rows such as `lap_records` are updated in the same transaction.
- Raw model evidence remains reachable through the linked result/attempt/artifact
  chain.

When a review decision confirms the model:

- `review_cases.status` becomes `resolved`.
- `review_cases.outcome` becomes `confirmed`.
- Canonical rows must remain consistent with the confirmed value.

Ignoring a case is not a model confirmation. It records that the case should not
block the operator workflow.

## Correction Persistence Contract

Approved model-error corrections are persisted in `review_corrections` using a
stable key based on image file, field, and lap index when the correction is
lap-scoped. The stable key must not depend on `lap_record_id`, because rebuild
can delete and recreate canonical lap rows.

Rebuild must re-apply persisted corrections before recalculating best laps,
system review cases, and system flags.

Normal Review refresh must also apply persisted corrections before candidate
generation. A corrected model-error value must not be rediscovered as a fresh
open case just because new lap rows were inserted or rebuilt before refresh.

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

`driver_name` trigger `numeric_prefix` covers 1-3 leading digits separated from the
name by whitespace, underscore, hyphen, or period. Examples:

```text
42 LionZera7559
250 CyanoticBoot9
```

## Review-owned image flags

Open Review cases may create matching system `image_flags` so DB Doctor can verify that review-visible problems and image-scoped evidence stay in sync. The Review case is the user-facing product object; the flag row is supporting infrastructure.

Resolving, ignoring, or reopening a Review case synchronizes the matching system flag status. Users do not resolve or edit raw flags directly through the normal GUI. Corrections must flow through Review decisions so `review_cases`, `review_corrections`, `lap_records`, run counters, and flag evidence remain consistent.

Review reasons stay canonical and product-facing: `dirty_lap`, `track`, `weather`, `race_class`, `car`, and `driver_name`. Any more specific cause belongs in `trigger` or `error_type`, not in a separate raw flag UX.
