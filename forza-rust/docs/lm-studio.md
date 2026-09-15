# LM Studio Backend

Status: current
Audience: developer, maintainer, LLM
Scope: `forza-lmstudio` — HTTP backend, models, load config, evidence.

## Flow (`backend.rs::extract`)

Per image: build chat payload → POST (single-flight lock per
`(api_base, model)` for load management) → parse → validate → semantic
check, with attempt kinds
`initial / transport_retry / json_retry / semantic_retry` up to `max_retries`,
backing off on transient statuses (429/5xx). Non-retryable 4xx end as
`http_error`. A 2xx with an undecodable body still records a `parse_error`
attempt (attempts are never silently lost).

## Inference concurrency (multi-worker runs)

The single-flight lock above covers model *management* only. Concurrent
*inference* requests are gated per run by `inference_concurrency`
(`forza-app` semaphore, capped at `workers`): local LM Studio fails
concurrent vision calls (HTTP 500 `failed to process mtmd chunk`), so the
default `1` serializes them while encode/persist/derive/finalize stay
parallel. Raise only for servers with parallel slots (llama-server
`--parallel`, vLLM, cloud APIs). Every image failure logs
`error_type: message` and lands in `error_type`/`error_message` columns for
`--retry-errors`.

Payload: `model / system_prompt / input / temperature / max_output_tokens`
(+ conditional `reasoning`); `max_tokens` config maps to `max_output_tokens`.
Timeouts: total = `timeout_read`, plus a dedicated `timeout_connect`
(lines in `BackendConfig`).

## Parse → repair → validate (`response.rs`, `json_repair.rs`)

Strict shape (`t`/`e` entries with `dr/ca/cl/bl`, lap times re-parsed);
semantic issues `track_empty` / `entries_empty` / `all_best_laps_null`
(valid numerics count, matching the validator). On parse failure the repair
pass (trailing commas, quote flavors, prose windowing) is tried once and used
only if it fully validates; `raw_response` evidence always keeps the original
text.

## Models & load config (`client.rs`, `load_config.rs`)

Model identity = `{id, path, display_name, key, model_key}`. `ensure_loaded`
reuses a compatible loaded instance (context length satisfied,
`physical_batch_size` uncomparable, `eval_batch_size`/flash/offload exact) or
POSTs `/models/load`.

## Overview snapshot (`runtime_status`)

Diagnostics Overview uses the real `RuntimeClient::runtime_status` (Python
parity), not a TCP ping: matched model display name, effective load line
(`ctx · eval · phys · flash · kv · parallel · experts`, with `(want …)`
mismatches), capabilities line (`vision · tool_use · reasoning=… allowed…`),
model info line (publisher through `max ctx`), and warnings. `parallel` /
`num_experts` are parsed for display only; compat checks are unchanged.
`build_overview_snapshot` (`forza-app`) drives it on a throwaway
current-thread runtime (sync worker threads only).

## Evidence

Every attempt persists encoded-image dimensions, runtime snapshot id,
redacted messages/config, canonical request hash, raw/parsed payloads, token
and timing stats — with the run's real `context_length`/`reasoning_mode`
(no hardcoded values). The GUI "Verbose log" checkbox adds a per-image
diagnostic line (`RunParams::verbose`): model, attempts, duration,
tokens/tps, encoded payload size, and DB ids.
