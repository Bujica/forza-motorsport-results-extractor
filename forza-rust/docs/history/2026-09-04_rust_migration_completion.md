# Rust migration completion record

Status: historical (frozen record — not a behavior contract)
Audience: maintainer, developer, LLM
Date: 2026-09-04
Scope: sign-off of the Python → Rust migration; what was verified, fixed,
and explicitly deferred.

## Verification performed

- Three independent bug-hunt audits (`forza-db`: 17 findings, `forza-app`:
  19, `forza-gui`: 19) plus parity sweeps of `pipeline/domain/lmstudio`
  against `forza/{pipeline,domain,lmstudio}` and `db/app/output/cli/gui`
  against `forza/{db,application,output,cli,gui}`. Every finding was
  checked against source before fixing; several audit claims were rejected
  on Python-parity evidence (dirty laps winning the frontier,
  `sanitize_driver_name` badge fallback, `M:99` lap times,
  `accepted_with_issues`, review-candidate table scope).
- Full suites green at sign-off: Python `pytest` (851), `cargo test
  --workspace`, `cargo clippy --workspace --all-targets -- -D warnings`,
  `cargo fmt --all --check`, DB doctor battery (~70 checks, OK).
- Production validation on a real database: sequential runs, `workers = 2`
  runs, force re-run, rebuild, external spreadsheet import, CSV/PDF export —
  doctor green throughout, including duplicate/flag/review paths.

## Fixed during the migration

- Multi-worker evidence corruption (`input_order` cross-writes; `MAX(id)+1`
  PK race → `AUTOINCREMENT` + main-thread pre-allocation; schema v2).
- Duplicate rows without doctor-required metadata; worker errors swallowed
  into "completed" runs with eternal `running` rows; hardcoded attempt
  metadata (`5000/off`); global rebuild counter clobber; stale-hash retry;
  run-id collisions; missing-row PK collision on reactivation.
- Review pipeline gap: runs never created cases/flags (Python did so in
  `_complete_run`) — now end-of-run `rebuild()` plus `sync_review_flags`
  (also on ignore/reopen); missing `rain_time_suspicious` rule wired.
- GUI: DB-before-file delete, UTF-8 log panic, review→detail wrong image,
  stale selection leak, `catch_unwind` job guard, filter desyncs, settings
  preview races, off-screen restore, PDF TOC links/rect/page numbers.
- LM Studio: lost 2xx-undecodable attempts, swallowed transport detail,
  ungated retry without backoff, optimistic preflight, model-identity and
  timeout wiring, slow-streak defaults, `json_repair` wired behind
  validate-only usage.
- Config/CLI: silent defaults, unvalidated ranges, `y/n` + `0` roundtrips,
  `--strict` vs `--debug`, honest `config-check`, exit codes (cancelled 130),
  CWD-relative DB resolution.

## Explicitly deferred (not bugs)

- **Records page** (performance dashboard): biggest absent feature; Best Laps
  covers export/import.
- **Settings editors**: no choice/spinbox widgets, no batch confirm.
- **Internal API surface**: scoped frontier recompute, `by_id` readers,
  reference upserts, model unload, transport-error reload — flows covered by
  other paths.
- **Cosmetic divergences**: CSV empty-file behavior, PDF whitespace
  trimming, `total_tokens` None semantics, INI rewrite fidelity.
- **Docs**: root `docs/` frozen as Python reference; Rust docs live in
  `forza-rust/docs/` (this tree).

## Residual risks

- `forza.exe`/`forza-gui.exe` must be rebuilt after every source change;
  stale binary + newer database yields `Incompatible user_version` by design.
- Never open one sqlite file with both implementations (separate schemas).
- Personal-data fixtures (`model_responses/`, `images/`) stay git-ignored;
  dependent tests skip gracefully without them.
