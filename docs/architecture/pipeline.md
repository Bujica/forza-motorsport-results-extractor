# Pipeline Architecture

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: extraction pipeline and LM Studio persistence flow
Last verified: 2026-06-05
Supersedes: pipeline notes embedded in developer guide
Related tests: `tests/test_extraction_persistence.py`, `tests/test_extraction_parallel.py`, `tests/test_extractor.py`

The pipeline converts one image file into persisted extraction evidence.

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
