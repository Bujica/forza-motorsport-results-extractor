# Database Architecture: 5. Core Tables

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: Database architecture shard generated from the former oversized `database.md` document
Last verified: 2026-06-14
Last verified: 2026-06-14

Back to index: [`../database.md`](../database.md).
## 5. Core Tables
The DDL below is the architecture contract. Implementation may use SQLModel as long as the effective SQLite schema and constraints match.

## Topic shards

| Document | Scope |
| --- | --- |
| `02-5-core-tables/01-5-1-extraction-runs.md` | Database Architecture: 5. Core Tables: 5.1. `extraction_runs` |
| `02-5-core-tables/02-5-5-model-runtime-snapshots.md` | Database Architecture: 5. Core Tables: 5.5. `model_runtime_snapshots` |
| `02-5-core-tables/03-5-9-lap-records.md` | Database Architecture: 5. Core Tables: 5.9. `lap_records` |

## Maintenance policy

Keep this file as an index. Add table-level detail to the topic shards, not to this file.
