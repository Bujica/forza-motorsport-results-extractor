//! Extraction backend: OpenAI-compatible-ish chat call to LM Studio with
//! adaptive retries (transport / json / semantic), attempt records, response
//! stats, and the performance slow-streak flag. Ported from
//! `forza/lmstudio/backend.py`.

use std::time::{Duration, Instant};

use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use crate::client::RuntimeClient;
use crate::error::LlmError;
use crate::load_config::{DesiredLoadConfig, NormalizedLoadConfig, load_config_compatible};
use crate::protocol::{AttemptStatus, ModelAttemptRecord, ModelExtractionResult, RequestKind};
use crate::json_repair::repair_json;
use crate::response::{parse_and_validate_response, semantic_retry_issues};

const TRANSIENT_STATUS: [u16; 7] = [409, 423, 429, 500, 502, 503, 504];
const RUNTIME_MAX_ATTEMPTS: usize = 5;

/// Global async mutex keyed by `(api_base, model)` to serialize model
/// management across all backend instances.  Matches Python's
/// `_model_lock` / `_MODEL_LOCKS` pattern so that concurrent workers
/// cannot unload each other's loaded instances.
type ModelLockMap = tokio::sync::Mutex<
    std::collections::HashMap<(String, String), std::sync::Arc<tokio::sync::Mutex<()>>>,
>;

static MODEL_LOCKS: std::sync::LazyLock<ModelLockMap> =
    std::sync::LazyLock::new(|| tokio::sync::Mutex::new(std::collections::HashMap::new()));

async fn model_lock(api_base: &str, model: &str) -> std::sync::Arc<tokio::sync::Mutex<()>> {
    let mut locks = MODEL_LOCKS.lock().await;
    let key = (api_base.to_string(), model.to_string());
    locks
        .entry(key)
        .or_insert_with(|| std::sync::Arc::new(tokio::sync::Mutex::new(())))
        .clone()
}

#[derive(Debug, Clone)]
pub struct BackendConfig {
    pub url: String,
    pub model: String,
    pub max_tokens: i64,
    pub temperature: f64,
    pub timeout_connect_secs: u64,
    pub timeout_read_secs: u64,
    pub max_retries: u32,
    pub system_prompt: String,
    pub context_length: i64,
    pub reasoning_mode: Option<String>,
}

impl BackendConfig {
    pub fn api_base(&self) -> String {
        let clean = self.url.trim_end_matches('/');
        if let Some(idx) = clean.find("/api/v1/") {
            return format!("{}/api/v1", &clean[..idx]);
        }
        if clean.ends_with("/api/v1") {
            return clean.to_string();
        }
        if let Some(idx) = clean.find("/v1/") {
            return format!("{}/api/v1", &clean[..idx]);
        }
        clean.to_string()
    }

    pub fn chat_url(&self) -> String {
        format!("{}/chat", self.api_base())
    }

    pub fn desired_load_config(
        &self,
        eval_batch_size: Option<i64>,
        physical_batch_size: Option<i64>,
        flash_attention: bool,
        offload_kv: bool,
    ) -> Value {
        let mut config = json!({
            "context_length": self.context_length,
            "flash_attention": flash_attention,
            "offload_kv_cache_to_gpu": offload_kv,
        });
        if let Some(eval) = eval_batch_size {
            config["eval_batch_size"] = json!(eval);
        }
        if let Some(phys) = physical_batch_size {
            config["physical_batch_size"] = json!(phys);
        }
        config
    }
}

#[derive(Debug, Clone)]
pub struct PerformancePolicy {
    pub tps_floor: f64,
    pub reload_elapsed_s: f64,
    pub reload_streak: i64,
}

impl Default for PerformancePolicy {
    // Python parity (`backend.py`): 20 tok/s floor, 45 s elapsed, streak 3.
    // A derived `Default` (0/0.0/0) made `elapsed_s > 0.0` always true, so
    // every call counted as slow and `reload_before_next` latched on after
    // the first image, forever.
    fn default() -> Self {
        Self {
            tps_floor: 20.0,
            reload_elapsed_s: 45.0,
            reload_streak: 3,
        }
    }
}

#[derive(Debug, Clone)]
pub struct RuntimeSnapshot {
    pub endpoint: String,
    pub configured_model: String,
    pub matched_model: Option<String>,
    pub loaded_model: Option<String>,
    pub instance_id: Option<String>,
    pub display_name: Option<String>,
    pub publisher: Option<String>,
    pub architecture: Option<String>,
    pub format: Option<String>,
    pub params_string: Option<String>,
    pub quantization: Option<String>,
    pub selected_variant: Option<String>,
    pub size_bytes: Option<i64>,
    pub max_context_length: Option<i64>,
    pub capabilities_json: Option<String>,
    pub desired_load_config_json: String,
    pub effective_load_config_json: Option<String>,
    pub health_ok: bool,
    pub health_message: String,
    pub model_matches_config: Option<bool>,
}

/// Slow-streak state machine (persisted fields land with Fase 8).
#[derive(Debug, Default)]
pub struct PerformanceTracker {
    pub slow_streak: i64,
    pub reload_before_next: bool,
}

impl PerformanceTracker {
    pub fn track(&mut self, policy: &PerformancePolicy, elapsed_s: f64, stats: &Value) {
        let tps = stats.get("tokens_per_second").and_then(Value::as_f64);
        let mut slow = false;
        if tps.is_some_and(|tps| tps < policy.tps_floor) {
            slow = true;
        }
        if elapsed_s > policy.reload_elapsed_s {
            slow = true;
        }
        self.slow_streak = if slow { self.slow_streak + 1 } else { 0 };
        if self.slow_streak >= policy.reload_streak {
            self.reload_before_next = true;
        }
    }
}

pub struct LMStudioBackend {
    cfg: BackendConfig,
    policy: PerformancePolicy,
    http: reqwest::Client,
    runtime: RuntimeClient,
    performance: PerformanceTracker,
    instance_id: Option<String>,
    load_config: Option<Value>,
}

impl LMStudioBackend {
    pub fn new(cfg: BackendConfig, performance: PerformancePolicy) -> Result<Self, LlmError> {
        // Total timeout stays read-bound, but the TCP/TLS connect phase gets
        // its own budget: previously `timeout_connect_secs` never reached the
        // chat client (only `list_models`), so slow connects were misbilled
        // to `timeout_read`.
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(cfg.timeout_read_secs))
            .connect_timeout(Duration::from_secs(cfg.timeout_connect_secs.max(1)))
            .build()
            .map_err(|e| LlmError::Runtime(format!("http client: {e}")))?;
        let runtime = RuntimeClient::new(&cfg.url, cfg.timeout_connect_secs);
        Ok(Self {
            policy: performance,
            cfg,
            http,
            runtime,
            performance: PerformanceTracker::default(),
            instance_id: None,
            load_config: None,
        })
    }

    pub fn performance(&self) -> &PerformanceTracker {
        &self.performance
    }

    /// Capture the runtime state used by the run lifecycle's preflight row.
    pub async fn preflight_snapshot(
        &self,
        desired: &DesiredLoadConfig,
    ) -> Result<RuntimeSnapshot, LlmError> {
        let desired_json = self.desired_load_config(desired);
        let models = self.runtime.list_models().await?;
        let model = models.iter().find(|model| {
            model.id == self.cfg.model
                || model.path == self.cfg.model
                || model.display_name == self.cfg.model
                || (!model.key.is_empty() && model.key == self.cfg.model)
                || (!model.model_key.is_empty() && model.model_key == self.cfg.model)
        });
        let Some(model) = model else {
            return Ok(RuntimeSnapshot {
                endpoint: self.cfg.url.clone(),
                configured_model: self.cfg.model.clone(),
                matched_model: None,
                loaded_model: None,
                instance_id: None,
                display_name: None,
                publisher: None,
                architecture: None,
                format: None,
                params_string: None,
                quantization: None,
                selected_variant: None,
                size_bytes: None,
                max_context_length: None,
                capabilities_json: None,
                desired_load_config_json: desired_json.to_string(),
                effective_load_config_json: None,
                health_ok: false,
                health_message: format!("Configured model not found ({})", self.cfg.model),
                model_matches_config: Some(false),
            });
        };
        // Present-but-unloaded must not claim healthy/compatible: with zero
        // loaded instances there is nothing to run against yet.
        let instance = model.loaded_instances.first();
        let loaded = instance.is_some();
        Ok(RuntimeSnapshot {
            endpoint: self.cfg.url.clone(),
            configured_model: self.cfg.model.clone(),
            matched_model: Some(model.id.clone()),
            loaded_model: instance.map(|_| model.id.clone()),
            instance_id: instance.map(|value| value.id.clone()),
            display_name: Some(model.display_name.clone()),
            publisher: Some(model.publisher.clone()),
            architecture: Some(model.architecture.clone()),
            format: Some(model.format.clone()),
            params_string: Some(model.params_string.clone()),
            quantization: Some(model.quantization.clone()),
            selected_variant: Some(model.selected_variant.clone()),
            size_bytes: model.size_bytes,
            max_context_length: model.max_context_length,
            capabilities_json: Some(model.capabilities.to_string()),
            desired_load_config_json: desired_json.to_string(),
            effective_load_config_json: instance.map(|value| value.config.to_string()),
            health_ok: loaded,
            health_message: if loaded {
                format!("{} model(s) available", models.len())
            } else {
                format!(
                    "model '{}' found but no instance loaded — load it before running",
                    self.cfg.model
                )
            },
            model_matches_config: Some(loaded),
        })
    }

    fn desired_load_config(&self, desired: &DesiredLoadConfig) -> Value {
        self.cfg.desired_load_config(
            desired.eval_batch_size,
            desired.physical_batch_size,
            desired.flash_attention,
            desired.offload_kv_cache_to_gpu,
        )
    }

    fn user_text(kind: RequestKind, detail: Option<&str>) -> String {
        let base = "Extract all lap results from this image.";
        match kind {
            RequestKind::JsonRetry => format!(
                "{base} Previous response was not valid JSON for the required schema. \
                 Return only one minified JSON object with no markdown or commentary."
            ),
            RequestKind::SemanticRetry => {
                let suffix = detail
                    .map(|d| format!(" Detected issue: {d}."))
                    .unwrap_or_default();
                format!(
                    "{base}{suffix} Re-read the visible EVENT RESULTS table, keep partial driver lists \
                     if the screenshot is partial, but do not return an empty entry list or all null \
                     best laps when lap times are visible."
                )
            }
            _ => base.to_string(),
        }
    }

    fn build_payload(&self, image_b64: &str, mime: &str, user_text: &str) -> Value {
        let model = self
            .instance_id
            .clone()
            .unwrap_or_else(|| self.cfg.model.clone());
        let mut payload = json!({
            "model": model,
            "system_prompt": self.cfg.system_prompt,
            "input": [
                {"type": "image", "data_url": format!("data:{mime};base64,{image_b64}")},
                {"type": "text", "content": user_text},
            ],
            "temperature": self.cfg.temperature,
            "max_output_tokens": self.cfg.max_tokens,
            "store": false,
        });
        if let Some(mode) = &self.cfg.reasoning_mode {
            payload["reasoning"] = json!(mode);
        }
        payload
    }

    fn request_config(payload: &Value) -> Value {
        json!({
            "temperature": payload.get("temperature"),
            "max_output_tokens": payload.get("max_output_tokens"),
            "reasoning": payload.get("reasoning"),
            "context_length": payload.get("context_length"),
            "model": payload.get("model"),
        })
    }

    fn redacted_messages(payload: &Value) -> Value {
        let items: Vec<Value> = payload
            .get("input")
            .and_then(Value::as_array)
            .map(|arr| {
                arr.iter()
                    .map(|item| {
                        if item.get("type").and_then(Value::as_str) == Some("image") {
                            json!({"type": "image", "data_url": "[image redacted]"})
                        } else {
                            item.clone()
                        }
                    })
                    .collect()
            })
            .unwrap_or_default();
        Value::Array(items)
    }

    #[allow(clippy::too_many_arguments)]
    fn request_hash(
        messages_redacted: &Value,
        request_config: &Value,
        source_file_hash: Option<&str>,
    ) -> String {
        let canonical = json!({
            "request_messages_json": messages_redacted,
            "request_config_json": request_config,
            "prompt_snapshot_id": Value::Null,
            "model": Value::Null,
            "source_file_hash": source_file_hash,
            "request_image_format": Value::Null,
            "request_image_mime_type": Value::Null,
            "request_image_width": Value::Null,
            "request_image_height": Value::Null,
            "request_image_bytes": Value::Null,
        });
        // Python: json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        let encoded = serde_json::to_string(&canonical).unwrap_or_default();
        let digest = Sha256::digest(encoded.as_bytes());
        format!("{:x}", digest)
    }

    /// Full extraction loop. `on_attempt` receives every attempt as it is
    /// recorded (persistence hook for Fase 8).
    pub async fn extract<F>(
        &mut self,
        image_b64: &str,
        mime: &str,
        _semantic_name: &str,
        file_hash: Option<&str>,
        on_attempt: &mut F,
    ) -> Result<ModelExtractionResult, LlmError>
    where
        F: FnMut(&ModelAttemptRecord),
    {
        let mut attempts: Vec<ModelAttemptRecord> = Vec::new();
        let mut kind = RequestKind::Initial;
        let mut detail: Option<String> = None;

        for attempt_no in 1..=self.cfg.max_retries {
            let user_text = Self::user_text(kind, detail.as_deref());
            let payload = self.build_payload(image_b64, mime, &user_text);

            let started = Instant::now();
            let response_result = {
                let mutex = model_lock(&self.cfg.api_base(), &self.cfg.model).await;
                let _lock = mutex.lock().await;
                self.http
                    .post(self.cfg.chat_url())
                    .timeout(Duration::from_secs(self.cfg.timeout_read_secs))
                    .json(&payload)
                    .send()
                    .await
            };

            let elapsed_ms = started.elapsed().as_millis() as i64;
            let (http_status, body, transport_detail): (
                Option<u16>,
                Option<Value>,
                Option<String>,
            ) = match response_result {
                Ok(resp) => {
                    let status = resp.status().as_u16();
                    match resp.json::<Value>().await {
                        Ok(v) => (Some(status), Some(v), None),
                        Err(e) => (Some(status), None, Some(format!("body decode: {e}"))),
                    }
                }
                Err(e) => (None, None, Some(format!("{e}"))),
            };

            let stats = body
                .as_ref()
                .and_then(|b| b.get("stats"))
                .cloned()
                .unwrap_or(Value::Null);

            // Transport failure path (preserve the real detail: timeout vs
            // DNS vs reset used to collapse into one useless string).
            let Some(status_code) = http_status else {
                let message = transport_detail
                    .clone()
                    .map(|d| format!("transport error: {d}"))
                    .unwrap_or_else(|| "transport error".to_string());
                let record = ModelAttemptRecord {
                    attempt_number: attempt_no as i64,
                    attempt_reason: kind.as_str().into(),
                    status: AttemptStatus::Error,
                    accepted: false,
                    rejected_reason: Some("transport_error".into()),
                    duration_ms: elapsed_ms,
                    error_code: Some("transport_error".into()),
                    error_message: Some(message.clone()),
                    retry_instruction_text: Some(user_text.clone()),
                    request_config_json: Some(Self::request_config(&payload).to_string()),
                    request_messages_json: Some(Self::redacted_messages(&payload).to_string()),
                    request_hash: Some(Self::request_hash(
                        &Self::redacted_messages(&payload),
                        &Self::request_config(&payload),
                        file_hash,
                    )),
                    ..Default::default()
                };
                on_attempt(&record);
                attempts.push(record);
                if attempt_no < self.cfg.max_retries {
                    kind = RequestKind::TransportRetry;
                    detail = Some(message);
                    continue;
                }
                break;
            };

            if !(200..300).contains(&status_code) {
                // Only transient statuses merit a transport retry: 4xx (other
                // than 429) is a caller bug that looping cannot fix.
                let retryable = status_code == 429 || (500..600).contains(&status_code);
                let detail_suffix = transport_detail
                    .as_deref()
                    .map(|d| format!(" ({d})"))
                    .unwrap_or_default();
                let message = format!("HTTP {status_code}{detail_suffix}");
                let record = ModelAttemptRecord {
                    attempt_number: attempt_no as i64,
                    attempt_reason: kind.as_str().into(),
                    status: AttemptStatus::Error,
                    accepted: false,
                    rejected_reason: Some(if retryable {
                        "transport_error"
                    } else {
                        "http_error"
                    }.into()),
                    http_status: Some(status_code as i64),
                    duration_ms: elapsed_ms,
                    error_code: Some(if retryable {
                        "transport_error"
                    } else {
                        "http_error"
                    }.into()),
                    error_message: Some(message),
                    retry_instruction_text: Some(user_text.clone()),
                    request_config_json: Some(Self::request_config(&payload).to_string()),
                    request_messages_json: Some(Self::redacted_messages(&payload).to_string()),
                    request_hash: Some(Self::request_hash(
                        &Self::redacted_messages(&payload),
                        &Self::request_config(&payload),
                        file_hash,
                    )),
                    ..Default::default()
                };
                on_attempt(&record);
                attempts.push(record);
                if retryable && attempt_no < self.cfg.max_retries {
                    kind = RequestKind::TransportRetry;
                    // Backoff so 500s aren't hammered in a tight loop.
                    let backoff_ms =
                        (200u64 << (attempt_no - 1).min(4)).min(5_000);
                    tokio::time::sleep(std::time::Duration::from_millis(backoff_ms)).await;
                    continue;
                }
                break;
            }

            // A 2xx with an undecodable body must still produce an attempt
            // record: `?` here used to lose the attempt entirely (no evidence
            // row, undercounted attempts, `Exhausted` never built).
            let Some(body) = body else {
                let message = format!("HTTP {status_code}: response body is not valid JSON");
                let record = ModelAttemptRecord {
                    attempt_number: attempt_no as i64,
                    attempt_reason: kind.as_str().into(),
                    status: AttemptStatus::Error,
                    accepted: false,
                    rejected_reason: Some("parse_error".into()),
                    http_status: Some(status_code as i64),
                    duration_ms: elapsed_ms,
                    error_code: Some("parse_error".into()),
                    error_message: Some(message.clone()),
                    retry_instruction_text: Some(user_text.clone()),
                    request_config_json: Some(Self::request_config(&payload).to_string()),
                    request_messages_json: Some(Self::redacted_messages(&payload).to_string()),
                    request_hash: Some(Self::request_hash(
                        &Self::redacted_messages(&payload),
                        &Self::request_config(&payload),
                        file_hash,
                    )),
                    parse_error: Some(message.clone()),
                    response_stats_json: Some(stats.to_string()),
                    ..Default::default()
                };
                on_attempt(&record);
                attempts.push(record);
                if attempt_no < self.cfg.max_retries {
                    kind = RequestKind::JsonRetry;
                    detail = Some(message);
                    continue;
                }
                break;
            };
            let content = output_text(&body);
            let instance_from_response = body
                .get("model_instance_id")
                .and_then(Value::as_str)
                .map(String::from);

            // Parse, then repair-and-retry once before giving up (Python
            // `parse → repair_json → parse`). The repaired value is only
            // used when it fully parses+validates; `raw_response` evidence
            // always keeps the original text, so a bad repair can never
            // corrupt stored evidence — worst case it also fails and the
            // original parse error is reported.
            let parsed_result = match parse_and_validate_response(&content) {
                Ok(value) => Ok(value),
                Err(original) => {
                    let repaired = repair_json(&content);
                    if repaired == content {
                        Err(original)
                    } else {
                        parse_and_validate_response(&repaired).map_err(|_| original)
                    }
                }
            };
            let parsed = match parsed_result {
                Ok(value) => value,
                Err(parse_error) => {
                    let record = ModelAttemptRecord {
                        attempt_number: attempt_no as i64,
                        attempt_reason: kind.as_str().into(),
                        status: AttemptStatus::Error,
                        accepted: false,
                        rejected_reason: Some("parse_error".into()),
                        http_status: Some(status_code as i64),
                        duration_ms: elapsed_ms,
                        error_code: Some("parse_error".into()),
                        error_message: Some(parse_error.clone()),
                        retry_instruction_text: Some(user_text.clone()),
                        request_config_json: Some(Self::request_config(&payload).to_string()),
                        request_messages_json: Some(Self::redacted_messages(&payload).to_string()),
                        request_hash: Some(Self::request_hash(
                            &Self::redacted_messages(&payload),
                            &Self::request_config(&payload),
                            file_hash,
                        )),
                        raw_response: Some(content.clone()),
                        parse_error: Some(parse_error.clone()),
                        response_stats_json: Some(stats.to_string()),
                        ..Default::default()
                    };
                    on_attempt(&record);
                    attempts.push(record);
                    if attempt_no < self.cfg.max_retries {
                        kind = RequestKind::JsonRetry;
                        detail = Some(parse_error);
                        continue;
                    }
                    break;
                }
            };

            let issues = semantic_retry_issues(&parsed);
            if !issues.is_empty() && attempt_no < self.cfg.max_retries {
                let record = ModelAttemptRecord {
                    attempt_number: attempt_no as i64,
                    attempt_reason: kind.as_str().into(),
                    status: AttemptStatus::Error,
                    accepted: false,
                    rejected_reason: Some("semantic_validation".into()),
                    http_status: Some(status_code as i64),
                    duration_ms: elapsed_ms,
                    error_code: Some("semantic_validation".into()),
                    error_message: Some(issues.join(";")),
                    retry_instruction_text: Some(user_text.clone()),
                    request_config_json: Some(Self::request_config(&payload).to_string()),
                    request_messages_json: Some(Self::redacted_messages(&payload).to_string()),
                    request_hash: Some(Self::request_hash(
                        &Self::redacted_messages(&payload),
                        &Self::request_config(&payload),
                        file_hash,
                    )),
                    raw_response: Some(content.clone()),
                    parsed_json: Some(parsed.to_string()),
                    validation_status: Some("retry".into()),
                    validation_issues_json: Some(json!(issues).to_string()),
                    response_stats_json: Some(stats.to_string()),
                    ..Default::default()
                };
                on_attempt(&record);
                attempts.push(record);
                kind = RequestKind::SemanticRetry;
                detail = Some(issues.join(","));
                continue;
            }

            // Accepted.
            let input_tokens = stats.get("input_tokens").and_then(Value::as_i64);
            let output_tokens = stats.get("total_output_tokens").and_then(Value::as_i64);
            let reasoning_tokens = stats.get("reasoning_output_tokens").and_then(Value::as_i64);
            let total_tokens = match (input_tokens, output_tokens) {
                (Some(i), Some(o)) => Some(i + o),
                (Some(i), None) => Some(i),
                (None, Some(o)) => Some(o),
                (None, None) => None,
            };
            let elapsed_s = started.elapsed().as_secs_f64();
            self.performance
                .track(&self.policy.clone(), elapsed_s, &stats);

            let request_config = Self::request_config(&payload);
            let messages_redacted = Self::redacted_messages(&payload);
            let record = ModelAttemptRecord {
                attempt_number: attempt_no as i64,
                attempt_reason: kind.as_str().into(),
                status: AttemptStatus::Ok,
                accepted: true,
                model_instance_id: instance_from_response.or_else(|| self.instance_id.clone()),
                http_status: Some(status_code as i64),
                duration_ms: elapsed_ms,
                retry_instruction_text: Some(user_text.clone()),
                request_config_json: Some(request_config.to_string()),
                request_messages_json: Some(messages_redacted.to_string()),
                request_hash: Some(Self::request_hash(
                    &messages_redacted,
                    &request_config,
                    file_hash,
                )),
                raw_response: Some(content.clone()),
                parsed_json: Some(parsed.to_string()),
                validation_status: Some(
                    if issues.is_empty() {
                        "accepted"
                    } else {
                        "accepted_with_issues"
                    }
                    .into(),
                ),
                validation_issues_json: (!issues.is_empty()).then(|| json!(issues).to_string()),
                response_stats_json: Some(stats.to_string()),
                input_tokens,
                output_tokens,
                total_tokens,
                reasoning_tokens,
                tokens_per_second: stats.get("tokens_per_second").and_then(Value::as_f64),
                time_to_first_token_s: stats
                    .get("time_to_first_token_seconds")
                    .and_then(Value::as_f64),
                model_load_time_s: stats.get("model_load_time_seconds").and_then(Value::as_f64),
                ..Default::default()
            };
            let accepted_attempt = record.clone();
            on_attempt(&record);
            attempts.push(record);

            return Ok(ModelExtractionResult {
                parsed,
                raw_response: content,
                accepted_attempt,
                all_attempts: attempts,
            });
        }

        Err(LlmError::Exhausted { attempts })
    }

    /// Ensure the configured model is loaded with a compatible load config.
    ///
    /// Serialized by a global async mutex keyed by `(api_base, model)` so
    /// that concurrent workers cannot race on `/models` / `/models/load` and
    /// unload each other's loaded instances.  Matches Python's
    /// `_model_lock` / `_MODEL_LOCKS` pattern.
    pub async fn ensure_loaded(&mut self, desired: &DesiredLoadConfig) -> Result<(), LlmError> {
        let lock = model_lock(&self.cfg.api_base(), &self.cfg.model).await;
        let _guard = lock.lock().await;

        let models = self.runtime.list_models().await?;
        // Same identity rule as preflight
        // (`id || path || display_name || key || model_key`): a narrower
        // match rejects configs that preflight just accepted.
        let Some(model) = models.iter().find(|m| {
            m.id == self.cfg.model
                || m.path == self.cfg.model
                || m.display_name == self.cfg.model
                || (!m.key.is_empty() && m.key == self.cfg.model)
                || (!m.model_key.is_empty() && m.model_key == self.cfg.model)
        }) else {
            return Err(LlmError::Runtime(format!(
                "configured model not found: {}",
                self.cfg.model
            )));
        };

        let compatible: Vec<&crate::client::LoadedInstance> = model
            .loaded_instances
            .iter()
            .filter(|inst| load_config_compatible(&inst.config, desired))
            .collect();

        if let Some(first) = compatible.first() {
            self.instance_id = Some(first.id.clone());
            self.load_config = Some(normalized_value(&first.config));
            return Ok(());
        }
        // Not loaded compatibly: load it now via POST /models/load.
        let load_payload = {
            let mut v = desired_as_value(desired);
            v["model"] = json!(self.cfg.model);
            v["echo_load_config"] = json!(true);
            v
        };
        let data: Value = self
            .runtime_post_with_backoff("/models/load", load_payload)
            .await?;
        self.instance_id = data
            .get("instance_id")
            .and_then(Value::as_str)
            .map(String::from)
            .or_else(|| Some(self.cfg.model.clone()));
        self.load_config = Some(
            data.get("load_config")
                .or_else(|| data.get("config"))
                .cloned()
                .unwrap_or_else(|| desired_as_value(desired)),
        );
        Ok(())
    }

    async fn runtime_post_with_backoff(
        &self,
        path: &str,
        payload: Value,
    ) -> Result<Value, LlmError> {
        let url = format!("{}{path}", self.cfg.api_base());
        let mut last_error = String::new();
        for attempt in 1..=RUNTIME_MAX_ATTEMPTS {
            let response = self
                .http
                .post(&url)
                .timeout(Duration::from_secs(self.cfg.timeout_read_secs))
                .json(&payload)
                .send()
                .await;
            match response {
                Ok(resp) => {
                    let status = resp.status().as_u16();
                    if TRANSIENT_STATUS.contains(&status) && attempt < RUNTIME_MAX_ATTEMPTS {
                        last_error = format!("{status} transient response from {url}");
                        runtime_backoff(attempt).await;
                        continue;
                    }
                    if !(200..300).contains(&status) {
                        return Err(LlmError::Http { status });
                    }
                    return resp
                        .json()
                        .await
                        .map_err(|e| LlmError::Runtime(e.to_string()));
                }
                Err(err) => {
                    last_error = err.to_string();
                    if attempt < RUNTIME_MAX_ATTEMPTS {
                        runtime_backoff(attempt).await;
                        continue;
                    }
                }
            }
        }
        Err(LlmError::Runtime(format!(
            "LM Studio runtime is not ready (model={}, endpoint={url}): {last_error}",
            self.cfg.model
        )))
    }
}

fn normalized_value(config: &Value) -> Value {
    let n: NormalizedLoadConfig = crate::load_config::normalized_load_config(config);
    json!({
        "context_length": n.context_length,
        "eval_batch_size": n.eval_batch_size,
        "physical_batch_size": n.physical_batch_size,
        "flash_attention": n.flash_attention,
        "offload_kv_cache_to_gpu": n.offload_kv_cache_to_gpu,
    })
}

fn desired_as_value(desired: &DesiredLoadConfig) -> Value {
    let mut v = json!({
        "context_length": desired.context_length,
        "flash_attention": desired.flash_attention,
        "offload_kv_cache_to_gpu": desired.offload_kv_cache_to_gpu,
    });
    if let Some(eval) = desired.eval_batch_size {
        v["eval_batch_size"] = json!(eval);
    }
    if let Some(phys) = desired.physical_batch_size {
        v["physical_batch_size"] = json!(phys);
    }
    v
}

fn output_text(data: &Value) -> String {
    if let Some(text) = data.get("output_text").and_then(Value::as_str) {
        return text.to_string();
    }
    let mut chunks: Vec<String> = Vec::new();
    if let Some(items) = data.get("output").and_then(Value::as_array) {
        for item in items {
            if let Some(content) = item.get("content").and_then(Value::as_str) {
                chunks.push(content.to_string());
                continue;
            }
            if let Some(parts) = item.get("content").and_then(Value::as_array) {
                for part in parts {
                    if let Some(text) = part.get("text").and_then(Value::as_str) {
                        chunks.push(text.to_string());
                    }
                }
            }
        }
    }
    if !chunks.is_empty() {
        return chunks.join("").trim().to_string();
    }
    if let Some(text) = data
        .get("choices")
        .and_then(Value::as_array)
        .and_then(|choices| choices.first())
        .and_then(|first| first.get("message"))
        .and_then(|m| m.get("content"))
        .and_then(Value::as_str)
    {
        return text.to_string();
    }
    serde_json::to_string(data).unwrap_or_default()
}

/// Exponential backoff for runtime endpoints: min(0.5 * 2^(n-1), 4s).
async fn runtime_backoff(attempt: usize) {
    let total = (0.5 * 2f64.powi(attempt as i32 - 1)).min(4.0);
    tokio::time::sleep(Duration::from_secs_f64(total)).await;
}
