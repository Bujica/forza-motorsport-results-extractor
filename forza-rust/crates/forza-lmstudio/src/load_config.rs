//! LM Studio load-config comparison semantics.
//! Ported from `forza/lmstudio/load_config.py`, including the
//! physical_batch_size uncomparability rule and the context_length
//! "at least as much" satisfaction.

use serde_json::Value;

/// Fields the /models response never echoes back (see module docs upstream).
pub const UNCOMPARABLE_LOAD_CONFIG_KEYS: &[&str] = &["physical_batch_size"];

#[derive(Debug, Clone, PartialEq, Default)]
pub struct DesiredLoadConfig {
    pub context_length: i64,
    pub eval_batch_size: Option<i64>,
    pub physical_batch_size: Option<i64>,
    pub flash_attention: bool,
    pub offload_kv_cache_to_gpu: bool,
}

fn aliases(key: &str) -> &'static [&'static str] {
    match key {
        "context_length" => &["context_length", "contextLength", "n_ctx", "nCtx"],
        "eval_batch_size" => &["eval_batch_size", "evalBatchSize"],
        "physical_batch_size" => &["physical_batch_size", "physicalBatchSize"],
        "flash_attention" => &["flash_attention", "flashAttention"],
        "offload_kv_cache_to_gpu" => &[
            "offload_kv_cache_to_gpu",
            "offloadKVCacheToGpu",
            "offloadKvCacheToGpu",
        ],
        _ => &[],
    }
}

fn value<'a>(config: &'a Value, key: &str) -> Option<&'a Value> {
    let obj = config.as_object()?;
    for alias in aliases(key) {
        if let Some(found) = obj.get(*alias) {
            return Some(found);
        }
    }
    None
}

fn int_or_none(value: Option<&Value>) -> Option<i64> {
    match value? {
        Value::Number(n) => n.as_i64().or_else(|| n.as_u64().map(|u| u as i64)),
        Value::String(s) => s.trim().parse::<i64>().ok(),
        _ => None,
    }
}

fn bool_or_none(value: Option<&Value>) -> Option<bool> {
    match value? {
        Value::Bool(b) => Some(*b),
        Value::Number(n) => n.as_i64().map(|i| i != 0),
        Value::String(s) => match s.trim().to_lowercase().as_str() {
            "true" | "1" | "yes" | "on" => Some(true),
            "false" | "0" | "no" | "off" => Some(false),
            _ => None,
        },
        _ => None,
    }
}

/// Normalized view of an instance config with alias resolution applied.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct NormalizedLoadConfig {
    pub context_length: Option<i64>,
    pub eval_batch_size: Option<i64>,
    pub physical_batch_size: Option<i64>,
    pub flash_attention: Option<bool>,
    pub offload_kv_cache_to_gpu: Option<bool>,
}

pub fn normalized_load_config(config: &Value) -> NormalizedLoadConfig {
    NormalizedLoadConfig {
        context_length: int_or_none(value(config, "context_length")),
        eval_batch_size: int_or_none(value(config, "eval_batch_size")),
        physical_batch_size: int_or_none(value(config, "physical_batch_size")),
        flash_attention: bool_or_none(value(config, "flash_attention")),
        offload_kv_cache_to_gpu: bool_or_none(value(config, "offload_kv_cache_to_gpu")),
    }
}

/// `context_length` is satisfied when effective >= desired; everything else is exact.
pub fn load_config_value_satisfies(key: &str, desired: i64, effective: Option<i64>) -> bool {
    if key == "context_length" {
        return effective.is_some_and(|v| v >= desired);
    }
    effective == Some(desired)
}

pub fn load_config_value_satisfies_bool(key: &str, desired: bool, effective: Option<bool>) -> bool {
    if key == "context_length" {
        return false;
    }
    effective == Some(desired)
}

/// Whether a loaded instance satisfies the desired configuration.
/// `physical_batch_size` is skipped entirely (uncomparable — never echoed back).
pub fn load_config_compatible(existing: &Value, desired: &DesiredLoadConfig) -> bool {
    let normalized = normalized_load_config(existing);
    load_config_value_satisfies(
        "context_length",
        desired.context_length,
        normalized.context_length,
    ) && match desired.eval_batch_size {
        None => true,
        Some(v) => load_config_value_satisfies("eval_batch_size", v, normalized.eval_batch_size),
    } && load_config_value_satisfies_bool(
        "flash_attention",
        desired.flash_attention,
        normalized.flash_attention,
    ) && load_config_value_satisfies_bool(
        "offload_kv_cache_to_gpu",
        desired.offload_kv_cache_to_gpu,
        normalized.offload_kv_cache_to_gpu,
    )
}
