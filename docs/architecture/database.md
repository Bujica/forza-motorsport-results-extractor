# Database Architecture

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: SQLite vNext table architecture, invariants, views, and write flow
Last verified: 2026-06-05
Supersedes: `docs/db_vnext_architecture.md`
Related tests: split DB Doctor service tests and split DB repository tests
Last verified: 2026-06-14

This file is an index for the SQL/DB vNext architecture after the clean-break removal. Detailed table contracts, invariants, DB Doctor rules, and migration notes are split into smaller topic files.

## Topic shards

| Document | Scope |
| --- | --- |
| `database/01-1-scope-and-goals.md` | Database Architecture: 1. Scope And Goals |
| `database/02-5-core-tables.md` | Database Architecture: 5. Core Tables |
| `database/03-6-reference-external-views-indexes.md` | Database Architecture: 6. Reference, External, And Indexes |
| `database/04-11-full-run-write-flow.md` | Database Architecture: 11. Full Run Write Flow |

## Maintenance policy

This index must stay small. Add detailed database architecture content to the topic shards above, not to this index.
