Implementation: Rust (forza-rust/) — current. Legacy Python (forza/) frozen at 0.21.0-beta.1.

# Pipeline Architecture

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: extraction pipeline and LM Studio persistence flow
Last verified: 2026-09-05
Supersedes: pipeline notes embedded in developer guide
Related tests: `cargo test --workspace` (run in `forza-rust/`); fixtures in `forza-rust/fixtures/` (`expected/` committed; `model_responses/` + `images/` git-ignored personal data)

The pipeline converts one image file into persisted extraction evidence.
Image discovery lives in `forza-pipeline` (`discovery::find_images`,
`planning::plan_images`, `hashing::file_hash`); pure parsing, ordering, and
normalization live in `forza-domain`. Model I/O goes through the
`forza-lmstudio` reqwest+tokio backend (`DesiredLoadConfig`,
`PerformancePolicy`); response cleaning, strict parse+validation, and JSON
repair live in `forza-lmstudio::response` / `forza-lmstudio::json_repair`.

## Flow

```text
ImageFile
  -> preprocessing and request payload
  -> LM Studio chat call
  -> raw response artifact/text
  -> parse and validation
  -> accepted extraction attempt
  -> extraction result
  -> lap records
```

## Retry Boundary

Retries create additional attempts. They must not overwrite evidence from prior
attempts. The accepted attempt is the source of canonical parsed result data.

## Failure Boundary

Operational failures before an image is submitted to chat are run-level
failures. Per-image extraction failures are created only when an image-specific
attempt/result exists.

## Run Lifecycle

`forza-app/src/services/extraction_runner.rs` drives runs via
`spawn_extraction` (`RunParams`/`RunControl`/`RunEvent`): sequential
single-worker extraction, or multi-worker parallel extraction with inputs,
results, and metadata pre-allocated on the main connection so workers never
insert inputs. The end of every run calls `rebuild()` (best laps + review
cases + system flags + per-run counters).
