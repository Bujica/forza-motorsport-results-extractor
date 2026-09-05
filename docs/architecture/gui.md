Implementation: Rust (forza-rust/) — current. Legacy Python (forza/) frozen at 0.21.0-beta.1.

# GUI Architecture

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: GUI structure and responsibility boundaries
Last verified: 2026-09-05
Supersedes: GUI architecture notes embedded in `docs/DEVELOPER_GUIDE.md`
Related tests: `cargo test -p forza-gui` (run in `forza-rust/`)

The GUI is a Slint front-end (`forza-gui.exe`). Pages live in
`forza-rust/crates/forza-gui/ui/pages/*.slint`: images, process, review,
best-laps, diagnostics, settings, logs, plus embedded image-detail and
image-debug views. There is NO Records page. There is no PySide6, no QThread,
and no Qt signals.

## Responsibilities

| Layer | Responsibility |
| --- | --- |
| Slint pages | Render widgets and emit user-intent callbacks. |
| `src/lib.rs` | Own screen state, wire callbacks, enqueue worker requests, apply responses. |
| `src/worker.rs` | Run slow database, filesystem, or LM Studio work off the UI thread: a long-lived worker thread handles each request on its own short-lived thread, and responses marshal back via `slint::invoke_from_event_loop`. |
| `src/detail_views.rs` | Apply image-detail / image-debug payloads to UI models. |
| `src/ui_state.rs` | UI-thread-local widget-adjacent state (models, row cache, selection). |
| `src/ui_persist.rs` | Persisted window geometry, splitter, and column state. |
| Read services | Query SQLite and return GUI row structs (via `forza-app` services). |
| Write services | Apply explicit mutations and emit pipeline events. |
| Application services | Own domain workflows shared by CLI and GUI (`forza-app`). |

## Refresh Model

Writers emit events after mutations. Callbacks refresh their view state from
SQLite through worker requests. Views should not infer persistence success
from local widget state.

## Navigation

Repeated review workflows should support keyboard and mouse operation. Primary
binary decisions use focused controls; rare actions remain available but less
prominent.
