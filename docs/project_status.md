# Project Status

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: current product state after the 0.20.0 diagnostics release
Last verified: 2026-06-18
Supersedes: scattered stage notes in implementation and history documents
Related tests: `python -m compileall -q forza`, `pytest`, `python -m forza maintenance db-doctor --json`

This document is the first orientation point for maintenance work. It states the
current released product posture and links to the authoritative contracts.

## Current Stage

The current product version is 0.20.0, the GUI diagnostics and image workflow polish release.
SQLite is the runtime source of truth for extraction runs, inputs, attempts, raw
model evidence, reviews, internal image flags, best laps, Community Records,
performance analytics, and reference catalog data. Legacy runtime JSON caches,
experimental Lab/workbench tooling, compatibility-only repair services,
unsupported image lifecycle states, and non-essential CLI surfaces have been
removed from the product package.

The GUI is the primary operator surface. Images is the normal workflow entry
point: operators synchronize the input folder, review physical-file inventory,
select images, process that selection, then resolve Review/Best Laps outcomes.
Process remains a run/progress surface plus explicit full-folder shortcut. Best
Laps owns PDF/CSV output and external spreadsheet import. Records summarizes
player performance, community-record coverage, car usage/dominance, progress,
filtered rivals, and absolute/relative comparison gaps. Diagnostics provides runtime Overview, image-centric Image Debug, DB Doctor, and Logs. The CLI remains only for essential operational commands: GUI launch,
config check, database upgrade/reset/status, and DB Doctor. LM Studio remains
the runtime model backend.

Raw `image_flags` are retained as SQL infrastructure for duplicate lifecycle,
Review lifecycle, and DB Doctor integrity checks. They are not a normal GUI
read/write surface; product UI paths route through Images inventory state,
duplicate-group relationships, Image Detail Review cases, and the Review queue.

## Current Architecture

| Area | Current document |
| --- | --- |
| Documentation policy | `docs/documentation_policy.md` |
| Database architecture | `docs/architecture/database.md` |
| Architecture overview | `docs/architecture/overview.md` |
| Contracts index | `docs/contracts/README.md` |
| GUI contract | `docs/contracts/gui.md` |
| Developer maintenance | `docs/developer/guide.md` |
| User workflows | `docs/user/guide.md` |
| Advanced GUI tools | `docs/user/advanced_tools.md` |
| Versioning contract | `docs/contracts/versioning.md` |

## Completed Clean-break Work

The 2026-06 SQL/GUI clean-break removed the old development and compatibility
surface while preserving product behavior:

- SQL-first runtime evidence and reference/community-record authority.
- GUI-first operator workflow.
- Essential-only CLI.
- DB Doctor current-schema integrity checks.
- Review, Best Laps, PDF export, Community Records, and reference catalog data.
- Active documentation split into maintainable topic shards.
- Oversized post-cut tests split by product area.
- Removed-surface tests consolidated into compact static guards.

The 0.17.1 patch removed the unused `v_best_laps` view, added Best Laps-focused
read indexes, reduced repeated Best Laps table resize work, and aligned GUI DB
creation with CLI DB upgrade by seeding SQL reference tracks/cars. This keeps
external spreadsheet imports working immediately after DB reset/recreation.

The 0.18.0 release completed the Images-first schema/workflow reset:

- Images is the primary inventory and selection surface.
- Process is run/progress control plus explicit full-folder shortcut.
- Physical image files use current path/name identity and SQL-backed lifecycle
  state.
- Duplicate groups are inventory state and expand after base image filters.
- Review-derived findings remain Review/Image Detail cases; raw flags are
  internal infrastructure.
- Best Laps reads current image identity and uses the simplified participation
  vocabulary.

The 0.19.0 release completed the Performance Records workflow:

- Records/Performance analytics live in an application service and load through
  a GUI worker.
- Records shows track/class/weather records, dry non-TCR community coverage,
  most-used cars, dominant cars, progress, and global rivals.
- Community-record import and filtered PDF/CSV generation remain owned by Best
  Laps.
- Process no longer duplicates output controls, and Best Laps no longer duplicates
  its table summary in a lower text panel.

The 0.20.0 release completed the GUI diagnostics and image workflow polish pass:

- Process uses `Run All` for full-folder execution and reports final total elapsed time.
- Images shows race metadata date in the inventory and Image Details supports previous/next navigation.
- Developer Tools was renamed to Diagnostics, and Records now sits directly below Best Laps.
- Image Debug is image-centric and replaces the former result-centric debug runtime/read/controller/view surface.
- Image Debug exposes screenshot metadata, extraction results, attempts, model response evidence, parsed data, laps/reviews, artifacts, runtime snapshots, and timeline evidence from SQL.

The 0.19.2 stabilization release completed the post-audit hardening pass:

- Encoded image payload metadata now records source image bytes instead of base64 length.
- Community Records imports create active dry snapshots and report rejected rows separately from warnings.
- Review dirty-lap noise is limited to best-lap-impacting dirty laps.
- Records rivals are filtered by the active Records view, and rival/community gaps show absolute and relative values.
- DB Doctor artifact and raw-evidence checks use set-based or batched SQL where possible and avoid unnecessary file hashing when size already differs.
- Image rename rollback validates filesystem postconditions before SQL mutation and verifies rollback cleanup.

Completed implementation plans are archived in:

```text
docs/history/2026-06-14_clean_break_removal_plan_completed.md
docs/history/2026-06-16_images_first_schema_plan_completed.md
docs/history/2026-06-18_0.19.2_stabilization_release.md
```

## Next Approved Work

No active implementation plan is open after the 0.20.0 diagnostics release. New work
must start with a focused issue or a new document under `docs/plans/` when it
changes product behavior, schema, or workflow contracts.

Candidate non-blocking follow-up areas:

- Decide whether `python -m forza run` remains a supported automation surface
  after GUI-only operation is validated.
- Evaluate Records/Performance usefulness after the local database contains more
  processed runs and broader external-record coverage.

## Known Issues

- No release-blocking issues are known after the 0.20.0 validation gates.

## Validation Gates

Use these gates when a change affects runtime contracts:

```bash
python -m compileall -q forza
pytest
python -m forza maintenance db-doctor --json
python scripts\c8_2_audit_docs_tests.py
python -m forza --help
python -m forza gui
```

GUI changes also require a manual launch and workflow-specific checks from the
relevant contract document.
