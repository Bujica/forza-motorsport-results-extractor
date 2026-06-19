# Architecture Index

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: index of structural design documents
Last verified: 2026-06-05
Supersedes: architecture links embedded in `docs/README.md`
Related tests: see contract documents

Architecture documents explain structure and rationale. Contracts define
required behavior.

| Document | Scope |
| --- | --- |
| `overview.md` | System-level package and data-flow overview. |
| `database.md` | Index for SQL/DB vNext architecture shards: schema, invariants, DB Doctor, views, and write flow. |
| `gui.md` | GUI layer structure and controller/view/service responsibilities. |
| `pipeline.md` | Extraction pipeline, LM Studio boundary, attempts, and persistence flow. |

Removed Lab/workbench architecture is archived under `../history/2026-06-14_lab_architecture_removed_by_clean_break.md`.
