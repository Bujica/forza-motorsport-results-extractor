# Development

Status: current
Audience: developer, LLM
Scope: working in `forza-rust/`.

## Toolchain

Pinned stable Rust via `forza-rust/rust-toolchain.toml`. MSRV
`rust-version = "1.88"` (edition 2024 + let-chains). All commands run with
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

Run the same gate locally before pushing via the versioned hook:

```sh
git config core.hooksPath .githooks   # one-time install
git push                              # pre-push runs fmt + clippy + test
```

Bypass only with reason: `SKIP_GUARD=1 git push`.

## Lint policy (`Cargo.toml [workspace.lints]`)

- `rust.unsafe_code = "forbid"` (the GUI crate opts out for Slint-generated
  code only; hand-written `unsafe` needs a `// SAFETY:` comment).
- `clippy.correctness = "deny"`; `suspicious`/`style`/`complexity`/`perf` =
  `"warn"` (groups sit at priority -1 so the individual allows below win).
- `clippy.unwrap_used`/`expect_used = "warn"`; tests allow both explicitly,
  production code uses `?`, `let-else`, or `unreachable!` with a documented
  invariant (`expect` is rejected by the pre-push hook).
- Every crate inherits via `[lints] workspace = true` except `forza-gui`
  (see its `Cargo.toml` comment). `missing_docs` stays off: 113 warnings in
  `forza-domain` alone (every `value_enum!` variant would need docs via a
  macro change) — key fallible APIs carry `# Errors` sections instead.

## Dependencies and profiles

- Shared third-party versions live in `[workspace.dependencies]`; crates use
  `dep.workspace = true` so upgrades stay in lockstep.
- `[profile.release]`: `opt-level 3`, `lto = "fat"`, `codegen-units = 1`,
  `strip = true`. `[profile.dev.package."*"]` optimizes dependencies in dev.

## Error conventions

- Library crates define `thiserror` enums with `#[source]`-preserving
  variants (`DbError::Sqlite/Io/Pool`, `EncodeError::Io/Image`,
  `LlmError::Transport`); message-complete cases (`Transaction`,
  `Runtime`, `Parse`) document why they carry no source.
- Binaries (`cli`/`gui`) use `anyhow` + `.context()`/`.with_context()` with
  the affected path/phase.
- `forza-app` services return `Result<_, String>` with operation context
  (`encode {path}: …`, `model load: …`, `open database {path}: …`).
- Row identities on the attempt/result path are newtypes (`db/src/ids.rs`:
  `RunId`, `ImageFileId`, `ExtractionResultId`, `AttemptId`, `RunInputId`)
  with `Display`/`AsRef<str>`/`ToSql`/`FromSql`; SQLite/CSV/Slint stay
  `String` at the boundary.

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
