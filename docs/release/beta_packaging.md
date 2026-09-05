# Windows Beta Packaging

Status: current
Target game: Forza Motorsport, 2023 release.
Target screenshot type: post-race Results screen.

Audience: maintainer
Lifecycle: beta release
Scope: Windows portable executable packaging
Last verified: 2026-09-05
Implementation: Rust (forza-rust/) — current. Legacy Python (forza/) frozen at 0.21.0-beta.1.

## Goal

Build a portable Windows beta ZIP that testers can unpack and run without a source checkout.
The bundle must include only product runtime files and must exclude developer-only directories.

## Bundle policy

Included (see the README.md bundle section, which stays authoritative):

- `forza-gui.exe` for GUI-first testing.
- `forza.exe` for explicit CLI and maintenance commands.
- Database migrations required by the application.
- Runtime reference data and starter configuration templates
  (`forza_config.ini.example` and related files).
- Empty runtime folders for `data/input`, `output/reports`, `output/logs`, and `output/exports`.

Excluded:

- `tools/`.
- `scripts/`.
- `tests/`.
- `.git/`.
- `.github/`.
- real SQLite databases.
- local screenshots, logs, reports, exports, prompt diagnostics, and debug artifacts.
- private external spreadsheets such as `DataFM.xlsx`.

There is no PyInstaller step and no `fmre-cli.exe` (that name never existed):
both executables are native Rust builds.

## Local build

From `forza-rust/` (Rust toolchain required):

```cmd
cd forza-rust
cargo build --release -p forza-cli -p forza-gui
```

Before release, the gates must be green:

```cmd
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
cargo fmt --all --check
```

Expected artifact:

```text
dist\ForzaMotorsportResultsExtractor-0.21.0-beta.1-windows-x64.zip
```

## Smoke test

From the unpacked bundle:

```cmd
forza.exe --help
forza.exe maintenance db-upgrade
forza.exe maintenance db-doctor --json
forza-gui.exe
```

## Notes

The beta uses native Rust builds: `forza-gui.exe` (Slint desktop app) plus
`forza.exe` (CLI maintenance and controlled runs) against the local SQLite
database. This keeps troubleshooting close to the shipped binaries with no
interpreter or packaging shim in between.
