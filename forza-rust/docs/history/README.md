# History (Rust)

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: index of completed Rust work records.

Completed work, audits, postmortems, and handoff evidence for the Rust
implementation live here, one dated file per record
(`YYYY-MM-DD_area_kind.md`, per root `docs/documentation_policy.md`).
Like root `docs/history/`, these are frozen records — never cite them as the
current behavior contract; current behavior lives in the topic docs and the
`forza-rust/crates/` source.

| Record | Covers |
| --- | --- |
| `2026-09-04_rust_migration_completion.md` | Migration sign-off: parity verification, deferred scope, residual risks. |
| `2026-09-10_post_migration_refinement.md` | Post-sign-off cycle: god-file splits, runner/discovery dedup, review refinement, backlog A–F, workers=2 incident + inference concurrency. |
| `2026-09-14_unified-race-class_and_skill_rules.md` | Unified `RaceClass` + skill-rules cycle: error context/chains, build policy, lints, casts, param structs, newtype IDs, doctests, proptest. |
