# Database Architecture: 11. Full Run Write Flow

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: Database architecture shard generated from the former oversized `database.md` document
Last verified: 2026-06-15

Back to index: [`../database.md`](../database.md).

## 11. Full Run Write Flow

```text
1. Create extraction_runs(status='running').
2. Upsert prompt_snapshots and attach prompt_snapshot_id to the run.
3. Synchronize supported physical input files into `image_files`.
4. Hash processable files and keep `image_files.file_hash` current without
   collapsing duplicate physical files.
5. Insert run_inputs for all considered files.
6. Perform LM Studio preflight.
7. Insert model_runtime_snapshots(snapshot_kind='preflight').
8. If preflight fails, fail the run operationally and stop.
9. For each processable run_input:
   a. Insert extraction_results(status='running').
   b. Write the attempt artifact and append extraction_attempts immediately for every real chat call.
   c. Register model_artifacts with sha256 and size_bytes.
   d. If accepted, update extraction_results and insert lap_records.
   e. If failed, update extraction_results with error_type/error_message.
   f. Commit the image result before pause/cancel checkpoints.
10. After image processing, rebuild global derived state atomically:
   a. lap_records.is_best_lap
   b. review_cases
   c. image_flags
   d. export_artifacts
11. Update run counters and mark completed/cancelled/failed.
```

Each image should have its own transaction boundary so one image failure does not poison the whole batch.

If the process exits unexpectedly, the next startup reconciles every process
input of the abandoned run to exactly one final result. Results that were still
pending/running become `cancelled`; already persisted attempts and artifacts are
retained.
