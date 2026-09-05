# GUI Architecture

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: GUI structure and responsibility boundaries
Last verified: 2026-06-05
Supersedes: GUI architecture notes embedded in `docs/DEVELOPER_GUIDE.md`
Related tests: `tests/test_gui_*`

The GUI uses a view/controller/service pattern.

## Responsibilities

| Layer | Responsibility |
| --- | --- |
| Views | Render widgets and emit user-intent signals. |
| Controllers | Own screen state, call read/write services, start workers, and translate events. |
| Workers | Run slow database, filesystem, or LM Studio work off the UI thread. |
| Read services | Query SQLite and return GUI dataclasses. |
| Write services | Apply explicit mutations and emit pipeline events. |
| Application/lab services | Own domain workflows shared by CLI and GUI. |

## Refresh Model

Writers emit events after mutations. Controllers listen for relevant events and
refresh their view state from SQLite. Views should not infer persistence success
from local widget state.

## Navigation

Repeated review workflows should support keyboard and mouse operation. Primary
binary decisions use focused controls; rare actions remain available but less
prominent.
