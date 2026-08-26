//! Core protocol types shared between the backend and persistence layers.

use serde::{Deserialize, Serialize};

pub const LMSTUDIO_BACKEND_NAME: &str = "lmstudio";

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AttemptStatus {
    #[default]
    Ok,
    Error,
}

/// Why this attempt exists: initial request or one of the retry reasons.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RequestKind {
    Initial,
    TransportRetry,
    JsonRetry,
    SemanticRetry,
}

impl RequestKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Initial => "initial",
            Self::TransportRetry => "transport_retry",
            Self::JsonRetry => "json_retry",
            Self::SemanticRetry => "semantic_retry",
        }
    }
}

/// One persisted attempt record (mirrors `extraction_attempts` columns).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ModelAttemptRecord {
    pub attempt_number: i64,
    pub attempt_reason: String,
    pub status: AttemptStatus,
    pub accepted: bool,
    pub rejected_reason: Option<String>,
    pub model_instance_id: Option<String>,
    pub http_status: Option<i64>,
    pub error_code: Option<String>,
    pub error_message: Option<String>,
    pub retry_instruction_text: Option<String>,
    pub request_config_json: Option<String>,
    pub request_messages_json: Option<String>,
    pub request_hash: Option<String>,
    pub raw_response: Option<String>,
    pub parsed_json: Option<String>,
    pub parse_error: Option<String>,
    pub validation_status: Option<String>,
    pub validation_issues_json: Option<String>,
    pub response_stats_json: Option<String>,
    pub duration_ms: i64,
    pub input_tokens: Option<i64>,
    pub output_tokens: Option<i64>,
    pub reasoning_tokens: Option<i64>,
    pub total_tokens: Option<i64>,
    pub tokens_per_second: Option<f64>,
    pub time_to_first_token_s: Option<f64>,
    pub model_load_time_s: Option<f64>,
}

/// Successful extraction outcome.
#[derive(Debug, Clone)]
pub struct ModelExtractionResult {
    pub parsed: serde_json::Value,
    pub raw_response: String,
    pub accepted_attempt: ModelAttemptRecord,
    pub all_attempts: Vec<ModelAttemptRecord>,
}
