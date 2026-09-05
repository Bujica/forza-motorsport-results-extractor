# Development

Status: current
Audience: developer, LLM
Scope: working in `forza-rust/`.

## Toolchain

Pinned stable Rust via `forza-rust/rust-toolchain.toml`. All commands run with
`forza-rust/` as working directory.

```cmd
cargo build -p forza-cli -p forza-gui
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
cargo fmt --all
```

Binaries land in `forza-rust/target/debug/` (or `release/`): `forza.exe`
(CLI) and `forza-gui.exe` (desktop app). Rebuild both before testing GUI/CLI
by hand — a stale binary against a newer database is the classic
`user_version` mismatch.

## Gates (CI mirrors these)

`.github/workflows/rust.yml` runs, on Windows:

1. `cargo fmt --all --check`
2. `cargo clippy --workspace --all-targets -- -D warnings`
3. `cargo test --workspace`

The workflow triggers on `forza-rust/**`, the workflow file itself, and root
`.gitattributes` (line endings affect byte-embedded assets — see below).

## Fixtures (`forza-rust/fixtures/`)

| Path | Status |
| --- | --- |
| `expected/` | Committed goldens (`domain_golden.json`, `output_golden.json`). |
| `model_responses/` | Git-ignored personal data (sampled LM Studio responses). Tests using it **skip gracefully** when absent. |
| `images/` | Git-ignored real screenshots. Never commit. |
| `python_outputs/` | Retired local-run snapshots (untracked). Nothing reads them. |

Rules: only synthetic or anonymized values in committed fixtures; never invent
fixture data to satisfy a test — fix the code or skip explicitly.

## Text assets are byte-sensitive

`crates/forza-*/src` embeds files via `include_str!` (`assets/*.txt|*.json`,
golden JSONs). One file is even sha256-hashed
(`default_prompt_snapshot_identity_matches_python`). Root `.gitattributes`
forces LF checkouts for these paths — a CRLF checkout changes the bytes and
breaks goldens only on that machine. Never weaken a golden to accommodate an
editor; fix the bytes.

## Python tree

`forza/` is frozen legacy. Do not add features there. Python behavioral rules
may still inform intent, but the Rust source is authoritative.
