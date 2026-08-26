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
use crate::response::{parse_and_validate_response, semantic_retry_issues};

const TRANSIENT_STATUS: [u16; 7] = [409, 423, 429, 500, 502, 503, 504];
const RUNTIME_MAX_ATTEMPTS: usize = 5;

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

#[derive(Debug, Clone, Default)]
pub struct PerformancePolicy {
    pub tps_floor: f64,
    pub reload_elapsed_s: f64,
    pub reload_streak: i64,
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
        let timeout_read = Duration::from_secs(cfg.timeout_read_secs);
        let http = reqwest::Client::builder()
            .timeout(timeout_read)
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
            let response_result = self
                .http
                .post(self.cfg.chat_url())
                .timeout(Duration::from_secs(self.cfg.timeout_read_secs))
                .json(&payload)
                .send()
                .await;

            let elapsed_ms = started.elapsed().as_millis() as i64;
            let (http_status, body): (Option<u16>, Option<Value>) = match response_result {
                Ok(resp) => {
                    let status = resp.status().as_u16();
                    match resp.json::<Value>().await {
                        Ok(v) => (Some(status), Some(v)),
                        Err(_e) => (Some(status), None),
                    }
                }
                Err(_e) => (None, None),
            };

            let stats = body
                .as_ref()
                .and_then(|b| b.get("stats"))
                .cloned()
                .unwrap_or(Value::Null);

            // Transport failure path.
            let Some(status_code) = http_status else {
                let message = "transport error".to_string();
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
                let message = format!("HTTP {status_code}");
                let record = ModelAttemptRecord {
                    attempt_number: attempt_no as i64,
                    attempt_reason: kind.as_str().into(),
                    status: AttemptStatus::Error,
                    accepted: false,
                    rejected_reason: Some("transport_error".into()),
                    http_status: Some(status_code as i64),
                    duration_ms: elapsed_ms,
                    error_code: Some("transport_error".into()),
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
                if attempt_no < self.cfg.max_retries {
                    kind = RequestKind::TransportRetry;
                    continue;
                }
                break;
            }

            let body = body.ok_or_else(|| LlmError::Parse("missing response body".into()))?;
            let content = output_text(&body);
            let instance_from_response = body
                .get("model_instance_id")
                .and_then(Value::as_str)
                .map(String::from);

            // Parse (+minimal repair), then validate.
            let parsed_result = parse_and_validate_response(&content);
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
    pub async fn ensure_loaded(&mut self, desired: &DesiredLoadConfig) -> Result<(), LlmError> {
        let models = self.runtime.list_models().await?;
        let Some(model) = models.iter().find(|m| m.id == self.cfg.model) else {
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
