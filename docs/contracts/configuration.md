# Configuration Contract

Implementation: Rust (forza-rust/) — current. Legacy Python (forza/) frozen at 0.21.0-beta.1.
Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: runtime configuration ownership and propagation
Last verified: 2026-09-05
Supersedes: configuration rules embedded in `docs/DEVELOPER_GUIDE.md`
Related tests: unit tests in `forza-rust/crates/forza-config` (`save.rs`, `settings` snapshot tests in `forza-app`)

Runtime configuration is owned by the live application configuration state.
GUI code and services must not keep stale path, model, or runtime settings
after Settings changes.

## Ownership

- `forza_config.ini` is parsed by the `forza-config` crate:
  `load_config(path, strict)` loads with documented defaults (a missing file
  yields all defaults plus a warning); `strict=true` aborts on the first
  invalid value, otherwise invalid values produce collected warnings and fall
  back to defaults.
- `validate_config` enforces vocabularies (`image_format`, `reasoning_mode`,
  registered prompt ids), non-empty identity/endpoint values
  (`lmstudio.url`, `lmstudio.model`, `user.gamertag`, path entries), numeric
  ranges, and explicit finiteness checks (`str::parse::<f64>` accepts
  NaN/inf, so every float bound is checked with `is_finite`).
- Unknown `[section] key` pairs produce warnings
  (`Unknown config key [...] ...: ignored (typo?)`); they are never applied
  silently.
- The GUI worker owns the live `AppConfig`
  (`forza-gui/src/worker.rs::WorkerContext.cfg: Mutex<AppConfig>`); settings
  saves update it in place so every handler observes the current
  configuration. There is no `GuiConfigState`.
- `forza.exe config-check` is the CLI gate: it loads leniently, prints every
  warning, and fails (non-zero exit) on ANY warning or validation error.

## GUI Rules

- Settings UI snapshot rows are built in
  `forza-app/src/services/settings.rs` (`settings_snapshot`): editable rows
  with key/name/value/status/editor/options, grouped into Paths,
  Backend / Model / Prompt, Runtime / Image / PDF / Validation, and UI.
  Numeric editors advertise min/max/step in `options`; path rows carry
  `ok` / `invalid` / `missing` status badges; pending edits are marked
  `pending` without touching the persisted config.
- The edit flow is `setting-edited` → `Request::PreviewSettings` (with a
  sequence number so stale concurrent previews are dropped) →
  `Request::SaveSettings`; the status bar shows the validation verdict
  (`Configuration is valid for execution.` or bulleted
  `Configuration errors:`).
- Readers, writers, and services that depend on changed paths or runtime
  settings must observe the worker-owned live config after a save.
- Settings exposes operator-editable runtime fields; database path and schema
  state diagnostics belong to the status bar, DB Doctor, and config file.
- Removed Lab/workbench paths, including `paths.benchmark_file`, must not be
  exposed as runtime configuration or Settings fields. The saver prunes
  obsolete keys (`output_dir`, `backend`, `ollama` section, and others — see
  `forza-config/src/save.rs::write_candidate`).

## Save Rules

- `save::candidate_config` builds the candidate from the on-disk file plus
  the change set and validates the whole candidate; invalid values reject
  the save without touching the file.
- `save::save_changes` writes a timestamped `.bak` backup
  (`forza_config.ini.YYYYmmdd-HHMMSS-ffffff.bak`), then writes atomically
  (temp file + rename) while preserving unknown sections/keys.
- An empty change set is rejected with `No changes to save.`; non-editable
  or unknown fields are rejected (`Field is not editable: ...`).

## Gamertag Propagation Rule

`user.gamertag` is not only a display setting — it is the primary identity key
for the best-lap frontier algorithm. The following rules apply to any code that
reads or uses the gamertag at runtime:

- Rust code must resolve the gamertag from the worker-owned live config at
  request time (see `WorkerContext::gamertag`) rather than capturing it as
  a frozen string at construction time. A frozen string becomes stale if the
  config is reloaded in the background without rebuilding the service.
- Changing `user.gamertag` in Settings must trigger a best-lap recompute
  immediately after the save succeeds. The recompute must complete and commit
  before the Best Laps view refreshes its cache. See `docs/contracts/best_laps.md`
  for the full gamertag recompute contract.
- `on_config_changed` handlers that do not rebuild their write service must
  still guarantee that the next write operation uses the updated gamertag.
  Reading the worker-owned live config at request time is the approved
  pattern.

## Runtime Rules

- LM Studio model, context length, reasoning mode, image format, and response
  stat settings live in configuration.
- Runs record the effective prompt/config/runtime evidence they use.
