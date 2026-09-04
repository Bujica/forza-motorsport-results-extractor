//! Runtime client for LM Studio metadata endpoints (`/api/v1/models`).
//! Ported from `forza/lmstudio/client.py`.

use serde_json::Value;

use crate::error::LlmError;
use crate::load_config::{DesiredLoadConfig, NormalizedLoadConfig, normalized_load_config};

#[derive(Debug, Clone, Default, PartialEq)]
pub struct LoadedInstance {
    pub id: String,
    pub config: Value,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct RuntimeModel {
    pub id: String,
    /// Raw `key` alias from the server row (Python matches configured models
    /// against `{id, path, display_name, key, model_key}`).
    pub key: String,
    /// Raw `model_key` alias from the server row.
    pub model_key: String,
    pub path: String,
    pub display_name: String,
    pub publisher: String,
    pub architecture: String,
    pub format: String,
    pub params_string: String,
    pub size_bytes: Option<i64>,
    pub max_context_length: Option<i64>,
    pub quantization: String,
    pub selected_variant: String,
    pub capabilities: Value,
    pub loaded_instances: Vec<LoadedInstance>,
}

impl RuntimeModel {
    pub fn label(&self) -> &str {
        if !self.display_name.is_empty() {
            &self.display_name
        } else {
            &self.id
        }
    }
}

#[derive(Debug, Clone)]
pub struct RuntimeDiagnostic {
    pub level: String,
    pub ok: bool,
    pub message: String,
    pub model_found: bool,
    pub loaded: bool,
    pub loaded_instances: usize,
    pub instance_id: String,
    pub warnings: Vec<String>,
}

fn api_base(url: &str) -> String {
    let clean = url.trim_end_matches('/');
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

fn model_rows(data: &Value) -> Vec<&Value> {
    match data {
        Value::Array(items) => items.iter().collect(),
        Value::Object(map) => ["models", "data"]
            .iter()
            .find_map(|key| map.get(*key).and_then(|v| v.as_array()))
            .map(|arr| arr.iter().collect())
            .unwrap_or_default(),
        _ => Vec::new(),
    }
}

fn str_field(row: &Value, keys: &[&str]) -> String {
    for key in keys {
        if let Some(value) = row.get(*key).and_then(Value::as_str)
            && !value.is_empty()
        {
            return value.to_string();
        }
    }
    String::new()
}

fn int_or_none(value: Option<&Value>) -> Option<i64> {
    value.and_then(|v| v.as_i64().or_else(|| v.as_str()?.parse().ok()))
}

pub struct RuntimeClient {
    url: String,
    http: reqwest::Client,
    timeout: std::time::Duration,
}

impl RuntimeClient {
    pub fn new(url: &str, timeout_secs: u64) -> Self {
        Self {
            url: url.to_string(),
            http: reqwest::Client::new(),
            timeout: std::time::Duration::from_secs(timeout_secs),
        }
    }

    fn models_url(&self) -> String {
        format!("{}/models", api_base(&self.url))
    }

    pub async fn list_models(&self) -> Result<Vec<RuntimeModel>, LlmError> {
        let response = self
            .http
            .get(self.models_url())
            .timeout(self.timeout)
            .send()
            .await
            .map_err(|e| LlmError::Transport(e.to_string()))?;
        let status = response.status();
        if !status.is_success() {
            return Err(LlmError::Http {
                status: status.as_u16(),
            });
        }
        let data: Value = response
            .json()
            .await
            .map_err(|e| LlmError::Transport(e.to_string()))?;

        let mut out = Vec::new();
        for row in model_rows(&data) {
            let id = str_field(row, &["key", "id", "model_key", "path"]);
            if id.is_empty() {
                continue;
            }
            let quantization = row
                .get("quantization")
                .and_then(Value::as_object)
                .and_then(|q| q.get("name"))
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string();
            let loaded_instances = row
                .get("loaded_instances")
                .and_then(Value::as_array)
                .map(|items| {
                    items
                        .iter()
                        .filter_map(|item| {
                            let inst_id = str_field(item, &["id", "instance_id"]);
                            if inst_id.is_empty() {
                                return None;
                            }
                            let config = item
                                .get("config")
                                .or_else(|| item.get("load_config"))
                                .cloned()
                                .unwrap_or(Value::Null);
                            Some(LoadedInstance {
                                id: inst_id,
                                config,
                            })
                        })
                        .collect()
                })
                .unwrap_or_default();

            out.push(RuntimeModel {
                id,
                key: str_field(row, &["key"]),
                model_key: str_field(row, &["model_key"]),
                path: str_field(row, &["path"]),
                display_name: str_field(row, &["display_name", "name"]),
                publisher: str_field(row, &["publisher"]),
                architecture: str_field(row, &["architecture"]),
                format: str_field(row, &["format"]),
                params_string: str_field(row, &["params_string", "params"]),
                size_bytes: int_or_none(row.get("size_bytes")),
                max_context_length: int_or_none(row.get("max_context_length")),
                quantization,
                selected_variant: str_field(row, &["selected_variant"]),
                capabilities: row.get("capabilities").cloned().unwrap_or(Value::Null),
                loaded_instances,
            });
        }
        Ok(out)
    }

    /// Health check: endpoint reachable and models listable.
    pub async fn health(&self) -> Result<String, LlmError> {
        let models = self.list_models().await?;
        Ok(format!("{} model(s) available", models.len()))
    }

    fn find_model<'a>(
        &self,
        models: &'a [RuntimeModel],
        configured: &str,
    ) -> Option<&'a RuntimeModel> {
        // Python parity: `{id, path, display_name, key, model_key}`.
        let wanted = configured.trim();
        models.iter().find(|model| {
            model.id == wanted
                || model.path == wanted
                || model.display_name == wanted
                || (!model.key.is_empty() && model.key == wanted)
                || (!model.model_key.is_empty() && model.model_key == wanted)
        })
    }

    /// Runtime status diagnostic with the same warning classes as Python.
    pub async fn runtime_status(
        &self,
        configured_model: &str,
        desired: &DesiredLoadConfig,
        reasoning_mode: Option<&str>,
    ) -> Result<RuntimeDiagnostic, LlmError> {
        let models = self.list_models().await?;
        let Some(model) = self.find_model(&models, configured_model) else {
            return Ok(RuntimeDiagnostic {
                level: "error".into(),
                ok: false,
                message: format!("Configured model not found ({configured_model})"),
                model_found: false,
                loaded: false,
                loaded_instances: 0,
                instance_id: String::new(),
                warnings: Vec::new(),
            });
        };

        let mut warnings: Vec<String> = Vec::new();
        let loaded = !model.loaded_instances.is_empty();
        let effective = if loaded {
            normalized_load_config(&model.loaded_instances[0].config)
        } else {
            NormalizedLoadConfig::default()
        };
        let instance_id = if loaded {
            model.loaded_instances[0].id.clone()
        } else {
            String::new()
        };

        if !loaded {
            warnings.push("Model is available but not loaded".into());
        } else if model.loaded_instances.len() > 1 {
            warnings.push(format!(
                "Multiple loaded instances ({})",
                model.loaded_instances.len()
            ));
        }

        if loaded
            && effective
                .context_length
                .is_some_and(|v| v < desired.context_length)
        {
            warnings.push(format!(
                "Loaded context_length mismatch: configured {}, loaded {}",
                desired.context_length,
                effective.context_length.unwrap_or(0)
            ));
        }
        if loaded
            && desired
                .eval_batch_size
                .is_some_and(|v| effective.eval_batch_size != Some(v))
        {
            warnings.push(format!(
                "Loaded eval_batch_size mismatch: configured {}",
                desired.eval_batch_size.unwrap_or(0)
            ));
        }
        if loaded
            && effective
                .flash_attention
                .is_some_and(|v| v != desired.flash_attention)
        {
            warnings.push("Loaded flash_attention mismatch".into());
        }
        if loaded
            && effective
                .offload_kv_cache_to_gpu
                .is_some_and(|v| v != desired.offload_kv_cache_to_gpu)
        {
            warnings.push("Loaded offload_kv_cache_to_gpu mismatch".into());
        }

        let vision = model.capabilities.get("vision").and_then(Value::as_bool);
        if vision == Some(false) {
            warnings.push("Model does not advertise vision capability".into());
        }
        if let Some(max_ctx) = model.max_context_length
            && desired.context_length > max_ctx
        {
            warnings.push(format!(
                "context_length {} exceeds max_context_length {max_ctx}",
                desired.context_length
            ));
        }
        if let Some(mode) = reasoning_mode {
            let allowed: Vec<&str> = model
                .capabilities
                .get("reasoning")
                .and_then(|r| r.get("allowed_options").or_else(|| r.get("allowed")))
                .and_then(Value::as_array)
                .map(|items| items.iter().filter_map(Value::as_str).collect())
                .unwrap_or_default();
            if !allowed.is_empty() && !allowed.contains(&mode) {
                warnings.push(format!(
                    "Reasoning mode mismatch: configured {mode}, model allows {}",
                    allowed.join(", ")
                ));
            }
        }

        let level = if warnings.is_empty() { "ok" } else { "warning" };
        let state = if loaded {
            "loaded"
        } else {
            "available, not loaded"
        };
        let message = if warnings.is_empty() {
            format!("{} · loaded and compatible", model.label())
        } else {
            format!(
                "{} · {state} · {} warning(s)",
                model.label(),
                warnings.len()
            )
        };
        Ok(RuntimeDiagnostic {
            level: level.into(),
            ok: level == "ok",
            message,
            model_found: true,
            loaded,
            loaded_instances: model.loaded_instances.len(),
            instance_id,
            warnings,
        })
    }
}
