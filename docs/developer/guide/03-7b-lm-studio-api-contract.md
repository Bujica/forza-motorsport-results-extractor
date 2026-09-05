# Developer Maintenance Guide: 7b. LM Studio API contract

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: Developer maintenance guidance shard generated from the former oversized `guide.md` document
Last verified: 2026-09-05
Implementation: Rust (forza-rust/) — current. Legacy Python (forza/) frozen at 0.21.0-beta.1.

Back to index: [`../guide.md`](../guide.md).

## 7b. LM Studio API contract

The project talks to LM Studio through the native REST API implemented in the
`forza-lmstudio` crate. Do not add OpenAI-compatible, Ollama, or generic
backend branches unless the whole runtime contract is deliberately redesigned.

Rust code entry points (`forza-rust/crates/forza-lmstudio/src/`):

```text
backend.rs      LMStudioBackend: async reqwest extract loop with
                initial/transport_retry/json_retry/semantic_retry
client.rs       RuntimeClient: model list and health metadata
load_config.rs  load-config compatibility (context, eval batch, flash, offload)
protocol.rs     ModelAttemptRecord, ModelExtractionResult, RequestKind records
response.rs     strict parse + validation of the short-key extraction JSON
json_repair.rs  one deterministic repair pass before json_retry
```

Run settings (model, URL, context, reasoning, eval batch, flash, offload,
timeouts, retries) come from `forza_config.ini` `[lmstudio]` via
`RunParams::from_config` (`forza-app`). Per-image debug log lines are emitted
when the run's `verbose` flag is set (GUI Process page `Debug` checkbox).
Attempts are persisted with the run's real `context_length`/`reasoning_mode`.

Configured URL:

```ini
[lmstudio]
url = http://127.0.0.1:1234/api/v1/chat
```

`BackendConfig::api_base()` derives the API base from the configured URL:

```text
http://127.0.0.1:1234/api/v1/chat -> http://127.0.0.1:1234/api/v1
http://127.0.0.1:1234/v1/chat/completions -> http://127.0.0.1:1234/api/v1
http://127.0.0.1:1234/api/v1 -> http://127.0.0.1:1234/api/v1
```

Runtime endpoints used:

```text
GET  /models        list available models and loaded instances
POST /models/load   load the configured model with explicit runtime config
POST /chat          submit the image + text extraction request
```

`RuntimeClient::list_models()` accepts the native `{"models": [...]}` shape,
legacy `{"data": [...]}`, or a raw list response, and maps rows to
`RuntimeModel` including model identity, metadata, capabilities, and loaded
instances. Health reporting stays non-mutating. The run preflight snapshot is
the non-mutating diagnostic; it uses only `GET /models`, compares desired load
parameters against effective loaded-instance config, and must not call
`/models/load`.

Model loading behavior:

- `ensure_loaded()` inspects `/models` and reuses one compatible loaded
  instance for the configured model.
- `ensure_loaded()` is protected by a global async mutex keyed by
  `(api_base, model)`. This is the single-flight guard that prevents two
  workers from loading the same LM Studio model simultaneously.
- Runtime model-control calls (`GET /models`, `POST /models/load`) retry
  short-lived connection, timeout, and transient LM Studio HTTP failures
  (`409`, `423`, `429`, `500`, `502`, `503`, `504`) with backoff before
  failing as an operational runtime error.
- Non-transient runtime failures fail immediately with model, endpoint, and
  desired load-config context. These failures belong to the run/backend, not
  to an individual image extraction result.
- If no compatible instance exists, `/models/load` is called with the desired
  load config (`model`, `echo_load_config = true`, plus context/batch/flags).
- Model identity matches on `id`, `path`, `display_name`, `key`, or
  `model_key`, in both preflight and `ensure_loaded`; keep the two in sync.

Load compatibility (`load_config.rs`):

- `context_length` satisfies when the loaded value is at least the desired
  value.
- `physical_batch_size` is uncomparable (the `/models` response never echoes
  it back) and must not block reuse.
- Alias forms (`contextLength`, `n_ctx`, `evalBatchSize`, `flashAttention`,
  offload variants) resolve to the same canonical fields.

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

`reasoning` is included only when `reasoning_mode` is set. Retry attempts
alter only the user text with a targeted instruction; they do not change the
schema contract. `max_output_tokens` carries the `[lmstudio]`
`max_completion_tokens` value.

Supported `[lmstudio]` options (via `forza-config` load + validate):

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
performance_tps_floor        slow-response watchdog token/s threshold (default 20.0)
performance_reload_elapsed_s slow-response watchdog elapsed threshold (default 45 s)
performance_reload_streak    consecutive slow responses before reload-before-next-image (default 3)
```

Supported `[image]` request-encoding options:

```text
max_width       resized request image width cap
encode_quality  JPEG/WebP quality, valid range 1..100
grayscale       HSL-lightness desaturation before encoding
```

Response parsing contract:

- `/chat` response text is read from `output_text`, then `output[]` message
  chunks, with a legacy `choices[]` fallback.
- The model must return the short-key JSON schema: `t` plus `e[]` entries.
- Parsing is strict JSON first, then one deterministic `repair_json` pass.
- `parse_and_validate_response()` in `response.rs` owns schema validation.
- Critical semantic issues (`track_empty`, `entries_empty`,
  `all_best_laps_null`) trigger `semantic_retry`.

Persistence/debug contract:

- `ModelExtractionResult` carries parsed JSON, raw text, the accepted attempt,
  and all attempts.
- Persistence stores final result data in `extraction_results` and per-call
  raw/debug evidence in `extraction_attempts` with the run's real
  `context_length`/`reasoning_mode`, the preflight runtime snapshot id, and
  the canonical request hash. Stored request messages keep the image redacted.

When extending API behavior:

1. Add new user-editable options to `forza-config` load, save, and validate.
2. Add GUI Settings support when the option changes runtime behavior.
3. Thread new run-affecting fields through `RunParams` and the attempt
   persistence path if they matter for later diagnosis.
4. Update tests for `LMStudioBackend`, `RuntimeClient`, and load-config
   compatibility.
5. Update this section and `forza_config.ini.example` in the same change.

When adding a new config field:

1. Add it to the config structs in `forza-config`.
2. Load and save it (preserving the existing ini shape).
3. Validate it in `validate_config()` if needed.
4. Add Settings UI support if user-editable.
5. Update docs if the field changes a public contract.

## 8. GUI architecture

The GUI is the Slint desktop app (`forza-gui.exe`, `forza-rust/crates/forza-gui/`).
Long-running extraction runs on worker threads driven by typed run events;
persistence and domain behavior live in `forza-app` services and `forza-db`
queries. The GUI worker protocol (`worker.rs` `Request`/`Response`) is the
boundary: image inventory, reviews, best laps, rebuild, image actions, image
debug, settings, and external-record import all cross it.

GUI pages (no Records page):

```text
Images           input-folder inventory, selected processing, flags, rename, export, safe deletion
Process          selected run config summary, run/rebuild controls, progress, operator log
Review           SQL review queue and correction actions
Best Laps        persisted frontier plus normalized external rows, CSV/PDF export, spreadsheet import
Diagnostics      overview, image debug, DB Doctor, logs (4 tabs)
Settings         grouped config editor with preview/save validation
```

Usability contracts:

- Run filters must display human-readable labels and keep `run_id` as the
  stable filter value for queries.
- Review binary decisions use a selected primary action: `Up`/`Down` navigate
  rows, `Left`/`Right` changes the primary action, and `Enter` applies it.
- Review writes must update the target lap/case and the matching system
  `image_flags` row in one transaction. Resolved dirty-lap cases must retain an
  auditable `resolution_note`, for example `decision:dirty=false`.
- Best Laps keeps `Source` limited to screenshot/external origin. Player-only
  filtering belongs to the gamertag label plus `Only this driver` checkbox.
- Shared image-detail entry points should be labelled `Image details`.
- Image Debug must keep raw model JSON and extracted pipeline data as separate
  panes; do not populate both from the same parsed object.
- Manual refresh controls are exceptions, not defaults. DB Doctor, Overview,
  and Best Laps import may expose them because they summarize database files,
  external spreadsheets, LM Studio, or other programs that can change outside
  the GUI.
- Process cancellation is two-step: the first click arms an inline
  confirmation; confirming stops after the current image. Pause blocks at safe
  checkpoints and cancel lifts pause.

## 9. GUI configuration contract

There is exactly one config source: `forza_config.ini`, loaded and validated
by `forza-config` (`load_config` + `validate_config`).

Mandatory rules:

- Long-running runs receive a start-time snapshot (`RunParams::from_config`).
  Later config changes must affect future runs only, not mutate active run
  state.
- Run-affecting `[lmstudio]` settings (model, URL, context, reasoning, eval
  batch, flash, offload, timeouts, retries) flow into the run only through
  `RunParams`.
- Settings edits preview and validate before saving; config-sensitive views
  update from the saved config without restarting the application.
- Views that display config-derived values must refresh those displays after
  a save.

## 10. GUI page loading

Slint instantiates page components on navigation (see `ui/main.slint`);
expensive state is loaded through GUI worker requests when a page is entered,
not at startup.

Rules:

- `Images` is the initial operator page and synchronizes the visible
  input-folder inventory.
- Expensive service reads for other pages are deferred until first page entry
  or first refresh.
- Do not replace on-navigation instantiation with eager loading of every page
  unless startup cost and side effects are deliberately re-evaluated.
