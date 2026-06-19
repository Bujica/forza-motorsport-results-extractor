# Configuration Contract

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: runtime configuration ownership and propagation
Last verified: 2026-06-16
Supersedes: configuration rules embedded in `docs/DEVELOPER_GUIDE.md`
Related tests: `tests/test_gui_settings_static.py`, config-aware GUI static tests

Runtime configuration is owned by the application configuration state. GUI
controllers and services must not keep stale path, model, or runtime settings
after Settings changes.

## GUI Rules

- `GuiConfigState` is the live GUI configuration owner.
- Config-aware controllers implement `on_config_changed(cfg, changes)`.
- Readers, writers, and services that depend on changed paths or runtime
  settings must be rebuilt when the relevant config key changes.
- Settings exposes operator-editable runtime fields; database path and schema
  state diagnostics belong to the status bar, DB Doctor, and config file.
- Debug settings visible in Settings must reflect persisted config rather than
  fixed UI defaults.
- Removed Lab/workbench paths, including `paths.benchmark_file`, must not be
  exposed as runtime configuration or Settings fields.

## Runtime Rules

- LM Studio model, context length, reasoning mode, image format, and response
  stat settings live in configuration.
- Runs record the effective prompt/config/runtime evidence they use.
