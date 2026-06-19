# Images And Files Contract

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: image file identity, file operations, rename, export, and deletion
Last verified: 2026-06-16
Supersedes: image-management rules scattered across user and developer guides
Related tests: `tests/test_gui_read_and_rename.py`, `tests/test_gui_image_management_static.py`, `tests/test_image_file_promoted_fields_static.py`

The Images-first workflow treats the input folder as the visible source of work.
File operations are explicit operator actions and must not be hidden side
effects of extraction.

This contract records the approved Images-first schema direction. Current
database tables use `image_files`; remaining internal `ImageFile*` Python
names are compatibility names, not schema contract names.

## Identity Rules

- `image_files.id` is the stable identity of one observed physical file.
- `image_files.current_path` is the authoritative filesystem location when the
  file is available. Runtime/domain schemas surface it as `str | None`, matching
  SQLite storage; filesystem code converts to `Path` only at operation edges.
- `image_files.current_name` is the operational display/source name.
- `image_files.file_hash` identifies content bytes and is indexed, not unique.
  Two physical files with identical bytes must remain two file rows sharing the
  same hash.
- `semantic_name` is a suggested/presentation filename. It must not replace the
  operational current filename unless the user explicitly renames the file.
- The reset schema must not preserve an `original_name` or `original_path`
  concept as an operational source of truth. First-seen evidence may be kept in
  audit/run-input history, but it must not compete with the current file name.
- Available image paths must resolve to existing files. Hash mismatch is
  integrity evidence that the file changed and must be surfaced; it must not
  silently rewrite a different file identity.
- Duplicate physical files remain visible in Images without collapsing into one row.
  A duplicate must carry `duplicate_of_image_file_id`, an active `duplicate`
  image flag, and a visible duplicate indicator in the Images table. Scan and
  delete flows must reconcile the group: available duplicates must not anchor to
  missing canonicals, deleting a canonical duplicate must promote a remaining
  file, and singleton groups must resolve active duplicate flags.
- `ImageFile.processing_status` is a GUI/read-model status derived from the
  latest `extraction_results.status` for the file, falling back to the latest
  `run_inputs` decision when no result exists. It is not an `image_files`
  column and must not compete with file inventory state.
- Files with no extraction result and no skipped latest input are
  `unprocessed`. Latest `pending` or `running` results are `processing`;
  latest `ok`, `error`, or `cancelled` results are shown as `processed_ok`,
  `processed_error`, or `cancelled`. A latest non-process run input with no
  result is shown as `skipped`.

## Images Surface Rules

Images is an inventory and processing surface, not a Review queue. Its filters
must stay tied to physical file state, derived processing state, best-lap
participation, run membership, track, and inventory indicators. Review reason
values such as `dirty_lap`, `track`, `weather`, `race_class`, `car`,
`gamertag`, and `driver_name` belong to Review, not to Images
filters.

The duplicate filter is an inventory-management filter. It must show complete
duplicate groups: the canonical image row plus its duplicate rows. It must not
show only rows currently marked as duplicates, because operators need the
canonical row visible while deciding which physical files to delete.

## Raw Image Metadata Retention

- `image_files.image_metadata_json` is retained as raw JSON-safe metadata
  exposed by the image decoder, such as EXIF, PNG, or text chunks when present.
- This field is not runtime source of truth and must not drive Images, Process,
  Review, Best Laps, Debug, or Records behavior.
- Product semantics discovered in this blob must be promoted to explicit columns
  and contracts before becoming behavior.
- The column is intentionally retained until real processing data proves whether
  raw image metadata is useful. The later decision is remove, document as a
  permanent forensic field, or promote specific keys to first-class schema.

## Rename Rules

- Extraction must not rename, move, or delete source screenshots.
- GUI rename is an explicit operation.
- Rename previews must be readable before confirmation.
- Rename updates only the current physical file path/name and keeps the same
  file row identity.
- Chronological race numbering should use race date/time evidence when
  available, falling back to stable deterministic ordering.
- Rename must preserve file content and should preserve filesystem modified time
  whenever possible.

## Deletion And Export Rules

- Export copies files; it does not change source identity.
- Deletion is explicit and requires selected image files in Images.
- Delete removes the physical file when it still exists inside the configured
  input folder and removes the related image database records. It must also
  reconcile `duplicate_of_image_file_id` and active `duplicate` flags for the
  affected content-hash group.
- If the selected physical file is already missing, Delete still removes the
  related image database records.
- Missing files are tracked as file state when the file disappeared outside an
  explicit app deletion action.
- `missing` means the file disappeared outside an explicit app deletion action.
- There is no persistent `deleted` file status in the active schema. Delete is
  a destructive asset-removal action, not a retained inventory lifecycle state.

## Internal image flag scope

`image_flags` is an internal SQL table used to couple image files, runs, extraction results, lap records, duplicate lifecycle, review lifecycle, and DB Doctor checks. It is not a normal image-management UX surface.

Images inventory must use image-file state and product relationships: `file_status`, `processing_status`, `best_lap_status`, run membership, track evidence from lap records, and duplicate-group relationships. It must not expose Review reason filters or raw `image_flags.flag_type` values as ordinary inventory filters.

Duplicate groups are product inventory state. The canonical/duplicate relationship is `image_files.duplicate_of_image_file_id`; duplicate flags are secondary lifecycle evidence and may be resolved or re-created by maintenance/reconciliation logic.

## Processing status

Image processing status is a GUI inventory projection, not an `image_files` column.
The persisted authority remains `run_inputs` plus `extraction_results`; Images read
paths derive `unprocessed`, `processing`, `processed_ok`, `processed_error`,
`cancelled`, and `skipped` from those causal rows. Domain `ImageFile` mirrors
physical image-file state and metadata only.

