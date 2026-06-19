# Raw Artifacts Contract

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: raw model response and debug artifact integrity
Last verified: 2026-06-05
Supersedes: raw-response integrity notes in history documents
Related tests: `tests/test_raw_response_and_review_linkage.py`, `tests/test_raw_response_record.py`

Raw model outputs are mandatory evidence, not optional debug convenience.

## Evidence Rules

- Every accepted attempt must retain raw response text in the database or a
  canonical `model_artifacts` row.
- Canonical raw artifacts must record `sha256` and `size_bytes`.
- Debug artifacts must be linked to the relevant run, image file, result, and
  attempt when those parents exist.
- Failed attempts must keep enough artifact evidence to explain the failure.

## Review Linkage

Model-error review cases must remain connected to accepted attempt evidence so
future prompt/model analysis can compare model output against human correction.
