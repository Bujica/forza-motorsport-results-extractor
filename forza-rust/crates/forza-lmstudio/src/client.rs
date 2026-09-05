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
    /// `"ctx … · eval … · …"` desired-vs-effective line (Python
    /// `_runtime_config_summary` parity).
    pub runtime_config_summary: String,
    /// `"vision=… · tool_use=… · reasoning=…"` line.
    pub capabilities_summary: String,
    /// `"publisher · arch · format · params · quant · size · max ctx …"` line.
    pub model_info_summary: String,
    /// Display name of the matched model (`"id -> Display"` overview line).
    pub matched_display: String,
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
                runtime_config_summary: "No loaded runtime config".into(),
                capabilities_summary: String::new(),
                model_info_summary: String::new(),
                matched_display: String::new(),
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
            runtime_config_summary: runtime_config_summary(desired, &effective),
            capabilities_summary: capabilities_summary(&model.capabilities, reasoning_mode),
            model_info_summary: model_info_summary(model),
            matched_display: model.display_name.clone(),
        })
    }
}

fn display_bool(value: Option<bool>) -> &'static str {
    match value {
        None => "unknown",
        Some(true) => "yes",
        Some(false) => "no",
    }
}

/// Desired-vs-effective load line (Python `_runtime_config_summary` parity).
pub fn runtime_config_summary(
    desired: &DesiredLoadConfig,
    effective: &NormalizedLoadConfig,
) -> String {
    let int_text = |v: Option<i64>| v.map(|n| n.to_string());
    // Python `str(bool)` spells `True`/`False`.
    let bool_text = |v: Option<bool>| {
        v.map(|b| {
            if b {
                "True".to_string()
            } else {
                "False".to_string()
            }
        })
    };
    let rows: [(&str, Option<String>, Option<String>); 7] = [
        (
            "ctx",
            Some(desired.context_length.to_string()),
            int_text(effective.context_length),
        ),
        (
            "eval",
            desired.eval_batch_size.map(|v| v.to_string()),
            int_text(effective.eval_batch_size),
        ),
        (
            "phys",
            desired.physical_batch_size.map(|v| v.to_string()),
            int_text(effective.physical_batch_size),
        ),
        (
            "flash",
            bool_text(Some(desired.flash_attention)),
            bool_text(effective.flash_attention),
        ),
        (
            "kv",
            bool_text(Some(desired.offload_kv_cache_to_gpu)),
            bool_text(effective.offload_kv_cache_to_gpu),
        ),
        ("parallel", None, int_text(effective.parallel)),
        ("experts", None, int_text(effective.num_experts)),
    ];
    let mut parts = Vec::new();
    for (label, wanted, loaded) in rows {
        if loaded.is_none() && wanted.is_none() {
            continue;
        }
        match (wanted, loaded) {
            (Some(w), Some(l)) if l != w => parts.push(format!("{label} {l} (want {w})")),
            (w, l) => parts.push(format!("{label} {}", l.or(w).unwrap_or_default())),
        }
    }
    if parts.is_empty() {
        return "No loaded runtime config".into();
    }
    parts.join(" · ")
}

fn format_size(value: Option<i64>) -> String {
    match value {
        None => String::new(),
        Some(bytes) => format!("{:.1} GiB", bytes as f64 / 1_073_741_824.0),
    }
}

/// `"publisher · arch · format · params · quant · size · max ctx …"` line
/// (Python `_model_info_summary` parity).
pub fn model_info_summary(model: &RuntimeModel) -> String {
    let mut parts = vec![
        model.publisher.clone(),
        model.architecture.clone(),
        model.format.clone(),
        model.params_string.clone(),
        model.quantization.clone(),
        format_size(model.size_bytes),
    ];
    if let Some(max_ctx) = model.max_context_length {
        parts.push(format!("max ctx {max_ctx}"));
    }
    if !model.selected_variant.is_empty() {
        parts.push(format!("variant {}", model.selected_variant));
    }
    let joined = parts
        .into_iter()
        .filter(|p| !p.is_empty())
        .collect::<Vec<_>>()
        .join(" · ");
    if joined.is_empty() {
        model.id.clone()
    } else {
        joined
    }
}

fn reasoning_options(capabilities: &Value) -> Vec<String> {
    capabilities
        .get("reasoning")
        .and_then(|r| r.as_object())
        .and_then(|map| map.get("allowed_options").or_else(|| map.get("allowed")))
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default()
}

/// `"vision=… · tool_use=… · reasoning=…"` line (Python
/// `_capabilities_summary` parity).
pub fn capabilities_summary(capabilities: &Value, reasoning_mode: Option<&str>) -> String {
    let vision = capabilities.get("vision").and_then(Value::as_bool);
    let tool_use = capabilities
        .get("trained_for_tool_use")
        .and_then(Value::as_bool);
    let mut parts = vec![
        format!("vision={}", display_bool(vision)),
        format!("tool_use={}", display_bool(tool_use)),
    ];
    let options = reasoning_options(capabilities);
    if !options.is_empty() {
        parts.push(format!(
            "reasoning={} allowed[{}]",
            reasoning_mode.unwrap_or("-"),
            options.join(", ")
        ));
    } else if let Some(default) = capabilities
        .get("reasoning")
        .and_then(|r| r.as_object())
        .and_then(|map| map.get("default"))
        .and_then(Value::as_str)
    {
        parts.push(format!("reasoning default={default}"));
    }
    parts.join(" · ")
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn summaries_match_python_format() {
        let desired = DesiredLoadConfig {
            context_length: 5120,
            eval_batch_size: Some(2048),
            physical_batch_size: None,
            flash_attention: true,
            offload_kv_cache_to_gpu: true,
        };
        let effective = normalized_load_config(&json!({
            "context_length": 262144,
            "eval_batch_size": 2048,
            "physical_batch_size": 512,
            "parallel": 4,
            "num_experts": 12,
            "flash_attention": true,
            "offload_kv_cache_to_gpu": true,
        }));
        assert_eq!(
            runtime_config_summary(&desired, &effective),
            "ctx 262144 (want 5120) \u{b7} eval 2048 \u{b7} phys 512 \u{b7} flash True \u{b7} kv True \u{b7} parallel 4 \u{b7} experts 12"
        );
        let caps = json!({
            "vision": true,
            "trained_for_tool_use": true,
            "reasoning": {"allowed_options": ["off", "on"]},
        });
        assert_eq!(
            capabilities_summary(&caps, Some("off")),
            "vision=yes \u{b7} tool_use=yes \u{b7} reasoning=off allowed[off, on]"
        );
        let model = RuntimeModel {
            id: "qwen3.6-35b-a3b".into(),
            publisher: "unsloth".into(),
            architecture: "qwen35moe".into(),
            format: "gguf".into(),
            params_string: "35B-A3B".into(),
            quantization: "Q2_K_XL".into(),
            size_bytes: Some(14_072_174_592),
            max_context_length: Some(262144),
            ..Default::default()
        };
        assert_eq!(
            model_info_summary(&model),
            "unsloth \u{b7} qwen35moe \u{b7} gguf \u{b7} 35B-A3B \u{b7} Q2_K_XL \u{b7} 13.1 GiB \u{b7} max ctx 262144"
        );
    }
}
