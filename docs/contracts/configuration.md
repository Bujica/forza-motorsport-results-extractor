# Configuration Contract

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: runtime configuration ownership and propagation
Last verified: 2026-06-21
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

## Gamertag Propagation Rule

`user.gamertag` is not only a display setting — it is the primary identity key
for the best-lap frontier algorithm. The following rules apply to any code that
reads or uses the gamertag at runtime:

- Write services must resolve the gamertag via a live provider callable (e.g. a
  zero-argument lambda closed over the current config object) rather than
  capturing it as a frozen string at construction time. A frozen string becomes
  stale if the config is reloaded in the background without rebuilding the
  service.
- Changing `user.gamertag` in Settings must trigger a best-lap recompute
  immediately after the save succeeds. The recompute must complete and commit
  before the Best Laps view refreshes its cache. See `docs/contracts/best_laps.md`
  for the full gamertag recompute contract.
- `on_config_changed` handlers that do not rebuild their write service must
  still guarantee that the next write operation uses the updated gamertag.
  Using a live provider callable is the approved pattern.

## Runtime Rules

- LM Studio model, context length, reasoning mode, image format, and response
  stat settings live in configuration.
- Runs record the effective prompt/config/runtime evidence they use.
