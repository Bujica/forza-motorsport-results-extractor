# Documentation Index

Status: current
Audience: user, developer, maintainer, LLM
Lifecycle: permanent
Scope: documentation navigation
Last verified: 2026-06-17
Supersedes: previous mixed documentation index
Related tests: none

This file is only a documentation map. Substantial content lives in topic files.
Architecture and developer guide indexes intentionally stay small; detailed material belongs in topic shards linked from each index.

## Start Here

| Document | Use |
| --- | --- |
| `project_status.md` | Current project stage, active known issues when any exist, and next approved work. |
| `documentation_policy.md` | Documentation naming, lifecycle, ownership, changelog, and update rules. |
| `../QUICK_GUIDE.md` | Fast install, launch, common commands, and package readme. |

## Directories

| Directory | Use |
| --- | --- |
| `user/` | User-facing guides. |
| `developer/` | Developer maintenance guide. |
| `contracts/` | Current behavior contracts. |
| `architecture/` | Current architecture and structural rationale. |
| `plans/` | Approved or proposed work not completed yet. |
| `history/` | Completed work, audits, postmortems, and handoff evidence. |

## Read Order For Maintenance

1. `project_status.md`
2. Relevant contract in `contracts/`
3. Relevant architecture document in `architecture/`
4. Relevant user or developer guide
5. Historical record only when past evidence is needed

## Source Of Truth

| Question | Read |
| --- | --- |
| What stage is the project in? | `project_status.md` |
| Where does documentation belong? | `documentation_policy.md` |
| How does the user operate the app? | `user/` |
| How should a developer maintain the project? | `developer/guide.md` |
| What behavior must code satisfy? | `contracts/` |
| How is the system structured? | `architecture/` |
| What changed in releases? | `../CHANGELOG.md` |
