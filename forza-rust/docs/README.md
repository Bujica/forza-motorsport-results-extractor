# Rust Implementation Docs

Status: current
Audience: developer, maintainer, LLM
Scope: the `forza-rust/` workspace — the current product code.

The Python tree in `forza/` is frozen at 0.21.0-beta.1 and documented under
root `docs/` (legacy reference — behavior rules there predate the port, code
pointers there do not apply here). When this documentation disagrees with
`forza-rust/crates/` source, the source wins.

## Map

| Document | Use |
| --- | --- |
| `development.md` | Toolchain, build/test/lint gates, fixtures, CI. Start here to work. |
| `architecture.md` | Crates, dependency direction, runtime flows (run, rebuild, GUI, LM Studio). |
| `database.md` | Schema v2, migration, doctor battery, tables, maintenance commands. |
| `reviews.md` | Candidate rules, case lifecycle, corrections, system flags, review queue. |
| `gui.md` | Slint pages, callbacks, worker Request/Response channel, filters, settings. |
| `lm-studio.md` | Backend contract: endpoints, retries, load config, evidence. |
| `output.md` | CSV/PDF plans, links, export flows. |
| `config.md` | `forza_config.ini`, validation, settings UI, save flow. |
| `contracts.md` | Checklist mapping the Python static-test guards to their Rust translations (Fase 0/7.5). |
| `gui_parity_handoff.md` | GUI parity plan and phase status (working doc). |
| `migration/` | Per-crate porting analyses — historical; the port is done, read current docs above for behavior. |

## Conventions used in these docs

- `forza.exe …` = CLI built from `crates/forza-cli` (`cargo build -p forza-cli`).
- `forza-gui.exe` = Slint desktop app from `crates/forza-gui`.
- Crate paths are relative to `forza-rust/crates/`.
- Gates that must stay green: `cargo fmt --all --check`,
  `cargo clippy --workspace --all-targets -- -D warnings`,
  `cargo test --workspace` (mirrored in `.github/workflows/rust.yml`).
