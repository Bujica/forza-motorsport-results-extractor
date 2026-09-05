# Developer Maintenance Guide: 7b. LM Studio API contract

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: Developer maintenance guidance shard generated from the former oversized `guide.md` document
Last verified: 2026-06-14

Back to index: [`../guide.md`](../guide.md).

## 7b. LM Studio API contract

The project talks to LM Studio through the native REST API implemented in `forza.lmstudio`. Do not add OpenAI-compatible, Ollama, or generic backend branches unless the whole runtime contract is deliberately redesigned.

Public code entry points:

```python
from forza.lmstudio import build_backend, LMStudioRuntimeClient
```

`build_backend(cfg)` returns `LMStudioNativeBackend`, which is the extraction backend used by `ExtractionService`. `LMStudioRuntimeClient` is a small metadata client used by GUI diagnostics for health checks and model metadata.

Configured URL:

```ini
[lmstudio]
url = http://127.0.0.1:1234/api/v1/chat
```

The code derives the API base from the configured URL:

```text
http://127.0.0.1:1234/api/v1/chat -> http://127.0.0.1:1234/api/v1
http://127.0.0.1:1234/v1/chat/completions -> http://127.0.0.1:1234/api/v1
http://127.0.0.1:1234/api/v1 -> http://127.0.0.1:1234/api/v1
```

Runtime endpoints used:

```text
GET  /models        list available models and loaded instances
POST /models/load   load the configured model with explicit runtime config
POST /models/unload unload duplicate or incompatible loaded instances
POST /chat          submit the image + text extraction request
```

`LMStudioRuntimeClient.list_models()` accepts the native `{"models": [...]}` shape, legacy `{"data": [...]}`, or a raw list response. It maps rows to `LMStudioModel` including model identity, metadata, capabilities, and loaded instances. `list_model_keys()` returns only model ids for comboboxes. `health()` returns `(ok, message)` and should stay non-mutating. `runtime_status(...)` is the non-mutating Overview diagnostic; it uses only `GET /models`, compares desired load parameters against effective loaded-instance config, and must not call `/models/load` or `/models/unload`.

Model loading behavior:

- `_ensure_loaded()` inspects `/models` and reuses one compatible loaded instance for the configured model.
- `_ensure_loaded()` and `_reload_model()` are protected by a shared lock keyed
  by `(api_base, model)`. This is the single-flight guard that prevents two
  workers from loading or unloading the same LM Studio model simultaneously.
- Runtime model-control calls (`GET /models`, `POST /models/load`, and
  `POST /models/unload`) retry short-lived connection, timeout, and transient
  LM Studio HTTP failures (`409`, `423`, `429`, `500`, `502`, `503`, `504`)
  with a short internal backoff before failing as an operational runtime error.
- Non-transient runtime failures fail immediately with model, endpoint, and
  desired load-config context. These failures belong to the run/backend, not to
  an individual image extraction result.
- Loaded duplicate compatible instances are unloaded.
- Loaded incompatible instances are unloaded.
- If no compatible instance exists, `/models/load` is called with the desired load config.
- `_reload_model()` unloads all loaded instances for that model and loads a fresh compatible instance.
- `workers=2+` depends on both the RunService preflight and this model lock:
  preflight prepares the model before the batch starts, while the lock keeps any
  later reload/load path serialized across worker backend instances.

Load config fields sent to `/models/load`:

```text
model
echo_load_config = true
context_length
eval_batch_size
physical_batch_size      optional, omitted when blank
flash_attention
offload_kv_cache_to_gpu
```

Chat payload sent to `/chat`:

```json
{
  "model": "<loaded instance id or configured model>",
  "system_prompt": "<active Forza extraction prompt>",
  "input": [
    {"type": "image", "data_url": "data:<mime>;base64,<payload>"},
    {"type": "text", "content": "Extract all lap results from this image."}
  ],
  "temperature": 0.0,
  "max_output_tokens": 800,
  "store": false,
  "reasoning": "off"
}
```

`reasoning` is included only when `reasoning_mode` is set. Retry attempts alter only the user text with a targeted instruction; they do not change the schema contract.

Supported `[lmstudio]` options:

```text
url                          native LM Studio API URL; /api/v1/chat is the normal value
model                        exact model id/key shown by LM Studio
max_completion_tokens        sent as max_output_tokens
temperature                  extraction temperature; production default is 0.0
image_format                 request payload format: png, jpeg, webp
timeout_connect              connect timeout in seconds
timeout_read                 read timeout in seconds
max_retries                  adaptive attempt budget
context_length               model load context length; blank means backend default
reasoning_mode               off, on, auto, low, medium, high
eval_batch_size              model load eval batch size; blank omits it
physical_batch_size          model load physical batch size; blank omits it
flash_attention              model load flag
offload_kv_cache_to_gpu      model load flag
performance_tps_floor        slow-response watchdog token/s threshold
performance_reload_elapsed_s slow-response watchdog elapsed threshold
performance_reload_streak    consecutive slow responses before reload-before-next-image
```

Supported `[image]` request-encoding options:

```text
max_width       resized request image width cap, valid range 640..4096
encode_quality  JPEG/WebP quality, valid range 1..100
grayscale       HSL-lightness desaturation before encoding
```

Response parsing contract:

- `/chat` response text is read from `output[]` message chunks.
- The model must return the short-key JSON schema: `t`, `tf`, `w`, and `e[]` with `dr`, `ca`, `cl`, `bl`.
- Parsing is strict JSON first, then one deterministic `json_repair` pass.
- `parse_and_validate_response()` in `forza.pipeline.model_response` owns schema validation.
- Critical semantic issues (`track_empty`, `entries_empty`, `all_best_laps_null`) can trigger `semantic_retry`.

Persistence/debug contract:

- `ModelExtractionResult` carries parsed JSON, raw text, elapsed time, token counts, request metadata, response stats, and all attempts.
- Persistence stores final result data in `extraction_results` and per-call raw/debug evidence in
  `extraction_attempts`. File-backed `model_artifacts` are registered artifacts only, not a hidden raw-response cache.

When extending API behavior:

1. Add new user-editable options to `LLMConfig`, `LMSTUDIO_DEFAULTS`, `load_config()`, and `validate_config()`.
2. Add GUI Settings support when the option changes runtime behavior.
3. Include new request/load fields in `ModelRequestMetadata`, `ModelExtractionAttempt`, or `ModelResponseStats` if they matter for later diagnosis.
4. Update tests for `LMStudioNativeBackend`, `LMStudioRuntimeClient`, and static GUI contracts.
5. Update this section and `forza_config.ini.example` in the same change.

When adding a new config field:

1. Add it to the relevant dataclass in `forza/config.py`.
2. Load it in `load_config()`.
3. Validate it in `validate_config()` if needed.
4. Add Settings UI support if user-editable.
5. Ensure `ConfigChangeSet` emits a stable dotted key.
6. Update `tests/gui/test_config_state_diff.py` expected keys.
7. Update docs if the field changes a public contract.

## 8. GUI architecture

The GUI follows a controller/view/worker split:

- Views own widgets and emit user-intent signals.
- Controllers translate signals into service/use-case calls.
- Workers own long-running work on `QThread`.
- Services own persistence and domain-facing behavior.
- `MainWindow` wires sections together and lazy-loads heavy pages.

Primary GUI sections:

```text
Images           input-folder inventory, selected processing, flags, rename, export, safe deletion
Process          selected run config summary, run/rebuild controls, progress, operator log
Review           SQL review queue and correction actions
Best Laps        persisted frontier plus normalized external rows
Records          external-record import plus performance/analytics views
Developer Tools  overview, image debug, DB Doctor, logs
Settings         grouped config table with typed editors and preview/save validation
```

Usability contracts:

- Run filters must display human-readable labels and keep `run_id` in combo
  item data for controller calls.
- Filter controls, comboboxes, tab labels, and action controls must size to
  expected text in the normal 1280px desktop layout; finite comboboxes use
  content-aware sizing or explicit minimum widths.
- Review binary decisions use a selected primary action: `Up`/`Down` navigate
  rows, `Left`/`Right` changes the primary action, and `Enter` applies it.
- Review writes must update the target lap/case and the matching system
  `image_flags` row in one transaction. Resolved dirty-lap cases must retain an
  auditable `resolution_note`, for example `decision:dirty=false`.
- Best Laps keeps `Source` limited to screenshot/external origin. Player-only
  filtering belongs to the gamertag label plus `Only this driver` checkbox.
- Shared image-detail entry points should be labelled `Image details`.
- Model Debug must keep raw model JSON and extracted pipeline data as separate
  panes; do not populate both from the same parsed object.
- Manual refresh controls are exceptions, not defaults. DB Doctor, Overview,
  and Records may expose them because they summarize database files, external
  spreadsheets, LM Studio, or other programs that can change outside the GUI.
  Logs must load internal read-only files on entry/configuration/events instead
  of exposing a reload button.

## 9. GUI configuration contract

There is exactly one live GUI configuration owner:

```python
forza.gui.config_state.GuiConfigState
```

Mandatory rules:

- `MainWindow` creates one `GuiConfigState`.
- Components registered through `connect_config_aware` must implement `on_config_changed(cfg, changes)`.
- Do not add `update_config(cfg)` compatibility hooks.
- No GUI controller may instantiate `ConfigFileService` directly.
- Long-running workers receive a start-time snapshot. Later config changes must affect future actions only, not mutate active worker state.
- Controllers that keep database readers/writers or other derived resources must rebuild them when `ConfigChangeSet.affects(...)` says the relevant key changed.
- Views that display config-derived values must refresh those displays through `on_config_changed`.
- Views with editable config-derived defaults should only update the field when the current text still equals the old default, so user-entered paths are not overwritten.

Typical controller pattern:

```python
def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet) -> None:
    self._cfg = cfg
    if changes.affects("paths.database_file"):
        self._reader.close()
        self._writer.close()
        self._reader = GuiReadService(cfg.database_file)
        self._writer = GuiWriteService(cfg.database_file)
```

Typical action-time config pattern:

```python
def start_run(self, ...) -> bool:
    cfg = self._config_state.current
    worker = SomeWorker(cfg=cfg, ...)
```

Use `changes.affects("paths")`, `changes.affects("paths.database_file")`, `changes.affects("llm")`, or exact keys depending on the dependency.

## 10. GUI lazy loading

`MainWindow` must not construct every major section at startup.

Rules:

- `Images` is loaded immediately because it is the initial operator page and
  synchronizes the visible input-folder inventory.
- Heavier pages are loaded on first navigation.
- Expensive service reads for unloaded pages are deferred until first page entry
  or first refresh.
- Dirty-section invalidation applies even before the page exists.
- When an unloaded dirty page is first opened, it must build from current controller/config state and then refresh normally.

Do not replace lazy loading with eager page construction unless startup cost and side effects are deliberately re-evaluated.

