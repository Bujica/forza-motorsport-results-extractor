# Reviews

Status: current
Audience: developer, maintainer, LLM
Scope: candidate rules → cases → corrections → flags → queue UI.

## Candidate rules (`forza-db/src/repositories/reviews.rs`)

Scanned from all lap rows; deduped by canonical business key:

| Reason | Scope | Trigger |
| --- | --- | --- |
| `dirty_lap` | lap | `model_marked_dirty` — only when the dirty lap is a best-lap winner (output-impacting only) |
| `weather` | image | `weather_unknown`, or `rain_time_suspicious` (best rain faster than best dry on track/class, via `laps.rs`) |
| `track` | image | `track_unknown`, `track_unresolved` (ambiguous), `track_not_in_reference` |
| `race_class` | image | `class_unknown`, `class_invalid` |
| `driver_name` | lap | `driver_name_empty`, `numeric_prefix`, `invalid_symbol` (see `forza-domain/src/review_rules.rs`) |
| `car` | lap | `car_empty`, `car_not_in_reference` |

Business keys: `{reason}:{image}:{lap_index}` (lap-scoped),
`{reason}:{image}` (image-scoped). Reference data is the union of compiled
assets (`forza-domain`) and the DB `reference_cars` catalog; confirming a
novel car seeds the catalog immediately and appends it to the shipped
`cars.txt` assets (best-effort) so regenerated databases stop redetecting it.

## Case lifecycle (`upsert_review_cases`)

- New keys → `open` cases (numbered from `MAX(case_number)+1`).
- Keys gone from candidates → `auto_resolved` (+ `resolved_at`,
  `resolution_note='no_longer_detected'`; `outcome` stays `pending` — the
  outcome vocabulary has no system value, so the GUI maps it for display).
- A returning condition **reopens** `auto_resolved → open` (outcome back to
  `pending`, evidence links refreshed). Operator `resolved` rows are never
  touched.
- There is no `ignore` state (removed deliberately): dismiss-without-decision
  does not exist; undecidable cases stay `open`, which is the honest
  representation. `status` vocabulary is `open|resolved|auto_resolved`,
  `outcome` is `pending|confirmed|model_error` (both CHECK-enforced).
- Cases are created automatically at end of every run and by manual Rebuild -
  never run a "rebuild" just to see reviews after a run.

## Corrections (`repositories/corrections.rs`)

`apply_manual_correction(case, field, value)` writes `review_corrections`
(image-scoped fields store `lap_index = NULL` - doctor-enforced), applies to
scope-matched laps, and resolves the case with a **classified outcome**:
`confirmed` when the value matches the model (normalized), else
`model_error` with an `error_type` (`{field}_wrong`,
`dirty_lap_false_positive/negative`) and `resolution_note=decision:{field}={value}`.
`apply_all` replays persisted corrections (rebuild/run path).
## System flags (`repositories/flags.rs::sync_review_flags`)

One active `system` flag per open case with an image target
(`lap:{img}:{type}:{idx}:{drv}:{trk}:{cls}` /
`image:{img}:{type}`); resolved cases get their flag resolved; stale system
flags resolve; operator flags are never touched. Synced on rebuild, run end,
and reopen. Doctor checks `open_reviews_missing_active_flag` /
`stale_active_review_flags` enforce this.

## Queue UI

Review page (`forza-gui/ui/pages/review.slint`): status (`open|resolved|all`)
/reason/outcome/run filters (index-clamped on model reload), keyboard nav,
per-reason apply stack, reopen, image-details jump (resolves by
`image_file_id`, never by list position). The outcome column and detail
panel show `auto_resolved` for system-closed rows (stored outcome stays
`pending` by vocabulary design); the outcome filter maps `auto_resolved`
and `pending` back to lifecycle status. Decide triggers full derived
refresh; reopen re-syncs flags.
