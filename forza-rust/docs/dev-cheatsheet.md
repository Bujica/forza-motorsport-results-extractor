# Dev Cheat Sheet

Status: current
Audience: developer (quick reference)
Scope: day-to-day commands and navigation for `forza-rust/`. Read this first, then open the deep docs only when a task needs them.

## The 5 commands of the day

Run with `forza-rust/` as the working directory.

| Command | What it does | When to run |
| --- | --- | --- |
| `cargo check --workspace` | Fast type-check, no binary built | After any edit — your instant feedback loop |
| `cargo clippy --workspace --all-targets -- -D warnings` | Lint; correctness errors are denied | Before committing |
| `cargo fmt --all` | Auto-format (idempotent) | When CI complains about formatting |
| `cargo test --workspace` | All unit + integration tests | After changes that touch logic |
| `cargo build -p forza-cli -p forza-gui` | Builds `forza.exe` and `forza-gui.exe` | Before testing GUI/CLI by hand |

One-liner gate (exactly what CI runs):

```sh
cargo fmt --all --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
```

## The crate map (memorize this, not the 34k lines)

Dependency direction — leaves at top, thin shells at bottom:

- `forza-domain` / `forza-pipeline` → pure rules, no I/O. Leaf crates.
- `forza-config`, `forza-db`, `forza-lmstudio`, `forza-output` → capabilities (config, sqlite, model client, csv/pdf).
- `forza-app` → orchestrates everything above.
- `forza-cli` / `forza-gui` → thin shells over `app`.

Rule: no cycles; keep cli/gui thin. Full table + run flow: [architecture.md](architecture.md).

## When X happens, do Y

| Symptom | Fix |
| --- | --- |
| GUI/CLI shows stale data (`user_version` mismatch) | `cargo build -p forza-cli -p forza-gui`, then re-run. A stale binary against a newer DB is the classic cause. |
| Golden hash test fails on *your* machine only | Line endings: `.gitattributes` forces LF for byte-embedded assets. Don't weaken the golden — fix the checkout bytes (see development.md). |
| `cargo fmt --check` fails in CI | Run `cargo fmt --all`, commit, re-push. |
| Pre-push hook blocks you | It ran fmt + clippy + test and something failed; read the output. Bypass only with reason: `SKIP_GUARD=1 git push`. |

## Navigation (don't read everything)

- **rust-analyzer** (VS Code): go-to-definition, hover for inferred types, find-references. The workspace is pinned in `.vscode/settings.json` (`rust.rustc_workspace`).
- Docs HTML persists in `target/doc/` once built — browse it without regenerating.
  - `cargo doc --no-deps -p <crate> --open`: just your crate(s), skips the third-party dep HTML (fast).
  - `cargo doc --open`: full docs incl. every dependency (slow first time — Slint's render/font tree is huge).
- Start here: [architecture.md](architecture.md) → [development.md](development.md) → per-crate as needed.

## Deep docs (read when you need them, not before)

| Doc | Covers |
| --- | --- |
| `architecture.md` | Crate layout, dependency direction, run flow |
| `development.md` | Toolchain, gates, lint policy, fixtures, error conventions |
| `contracts.md` / `database.md` | Data contracts + schema (`SCHEMA_VERSION = 2`) |
| `plans/` | Dated change plans — the backlog of in-flight work |
