//! LM Studio protocol, runtime client, extraction backend, and response
//! parsing/validation/repair. Ported from `forza/lmstudio/*` and
//! `forza/pipeline/model_response.py`.

pub mod backend;
pub mod client;
pub mod error;
pub mod json_repair;
pub mod load_config;
pub mod protocol;
pub mod response;

pub use backend::{LMStudioBackend, RuntimeSnapshot};
pub use client::{RuntimeClient, RuntimeModel};
pub use error::LlmError;
pub use protocol::{AttemptStatus, ModelAttemptRecord, ModelExtractionResult, RequestKind};

/// Registered prompt ids with embedded prompt text.
pub mod prompts {
    /// Default prompt id (matches Python `DEFAULT_PROMPT_ID`).
    pub const DEFAULT_PROMPT_ID: &str = "user_header_shaped_v1";

    /// System prompt text, byte-identical to the Python baseline.
    pub const USER_HEADER_SHAPED_V1: &str =
        include_str!("../../../assets/prompt_user_header_shaped_v1.txt");

    pub fn get_system_prompt(prompt_id: &str) -> Option<&'static str> {
        match prompt_id {
            DEFAULT_PROMPT_ID => Some(USER_HEADER_SHAPED_V1),
            _ => None,
        }
    }

    pub fn content_hash(text: &str) -> String {
        use sha2::{Digest, Sha256};
        let digest = Sha256::digest(text.as_bytes());
        format!("{:x}", digest)
    }

    /// Hash the same canonical prompt payload used by Python's lifecycle
    /// service (`json.dumps(..., sort_keys=True, ensure_ascii=True)`).
    pub fn payload_hash(system_text: &str) -> String {
        let canonical = format!(
            "{{\"response_schema_json\":null,\"system_text\":{},\"user_text_template\":null}}",
            ascii_json_string(system_text)
        );
        content_hash(&canonical)
    }

    pub fn snapshot_id(prompt_id: &str) -> String {
        match get_system_prompt(prompt_id) {
            Some(text) => format!("{prompt_id}:{}", payload_hash(text)),
            None => format!("{prompt_id}:missing"),
        }
    }

    fn ascii_json_string(text: &str) -> String {
        let mut out = String::from("\"");
        for ch in text.chars() {
            match ch {
                '"' => out.push_str("\\\""),
                '\\' => out.push_str("\\\\"),
                '\u{08}' => out.push_str("\\b"),
                '\u{0c}' => out.push_str("\\f"),
                '\n' => out.push_str("\\n"),
                '\r' => out.push_str("\\r"),
                '\t' => out.push_str("\\t"),
                ch if ch.is_ascii_control() => out.push_str(&format!("\\u{:04x}", ch as u32)),
                ch if ch.is_ascii() => out.push(ch),
                ch => out.push_str(&format!("\\u{:04x}", ch as u32)),
            }
        }
        out.push('"');
        out
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn default_prompt_snapshot_identity_matches_python() {
        assert_eq!(
            crate::prompts::payload_hash(crate::prompts::USER_HEADER_SHAPED_V1),
            "0a9cd9bab7f7d8425f4de98b27492f6ba16ed0b5be0eb997e6b897c64c945977"
        );
        assert_eq!(
            crate::prompts::snapshot_id(crate::prompts::DEFAULT_PROMPT_ID),
            "user_header_shaped_v1:0a9cd9bab7f7d8425f4de98b27492f6ba16ed0b5be0eb997e6b897c64c945977"
        );
    }
}
