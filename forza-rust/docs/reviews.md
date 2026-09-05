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
`{reason}:{image}` (image-scoped). Reference data comes from compiled assets
(`forza-domain`), not DB-seeded customs.

## Case lifecycle (`upsert_review_cases`)

- New keys → `open` cases (numbered from `MAX(case_number)+1`).
- Keys gone from candidates → `auto_resolved`. Operator `resolved`/`ignored`
  states are preserved (never overwritten by refresh).
- Cases are created automatically at end of every run and by manual Rebuild —
  never run a "rebuild" just to see reviews after a run.

## Corrections (`repositories/corrections.rs`)

`apply_manual_correction(case, field, value)` writes `review_corrections`
(image-scoped fields store `lap_index = NULL` — doctor-enforced), applies to
scope-matched laps, and resolves the case (`resolved`/`confirmed`).
`apply_all` replays persisted corrections (rebuild/run path).

## System flags (`repositories/flags.rs::sync_review_flags`)

One active `system` flag per open case with an image target
(`lap:{img}:{type}:{idx}:{drv}:{trk}:{cls}` / `image:{img}:{type}`); resolved
cases get their flag resolved; stale system flags resolve; operator flags are
never touched. Synced on rebuild, run end, ignore, and reopen. Doctor checks
`open_reviews_missing_active_flag` / `stale_active_review_flags` enforce this.

## Queue UI

Review page (`forza-gui/ui/pages/review.slint`): status/reason/outcome/run
filters (index-clamped on model reload), keyboard nav, per-reason apply
stack, ignore/reopen, image-details jump (resolves by `image_file_id`, never
by list position). Decide triggers full derived refresh; ignore/reopen
re-sync flags.
