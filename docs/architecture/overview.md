# Architecture Overview

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: system-level structure and source-of-truth overview
Last verified: 2026-06-05
Supersedes: high-level architecture notes scattered across developer guide
Related tests: `python -m pytest -q`

Forza Screenshot Extractor is a desktop-first application that processes Forza
Motorsport race-result screenshots with a local LM Studio vision model, stores
runtime state in SQLite, supports human review, and exports best-lap records.

## Primary Flow

```text
data/input images
  -> image inventory
  -> extraction run
  -> LM Studio attempts
  -> raw artifacts and parsed results
  -> lap_records
  -> review cases and image flags
  -> rebuild/recompute
  -> best-lap views and exports
```

## Package Roles

| Package | Role |
| --- | --- |
| `forza.application` | Orchestration services for runs, rebuild, images, DB Doctor, export, and config. |
| `forza.db` | SQLModel entities, migrations, repositories, and SQLite connection helpers. |
| `forza.gui` | PySide6 views, controllers, workers, and GUI read/write services. |
| `forza.lmstudio` | Native LM Studio REST API boundary. |
| `forza.pipeline` | Image processing and extraction orchestration helpers. |
| `forza.domain` | Domain rules that should be independent of UI and persistence. |
| `forza.output` | Export and report generation. |

## Authority Order

When sources disagree:

1. Contracts in `docs/contracts/` define intended behavior.
2. Architecture in `docs/architecture/` explains structure.
3. `docs/project_status.md` identifies known issues.
4. History explains how the project reached the current state.
