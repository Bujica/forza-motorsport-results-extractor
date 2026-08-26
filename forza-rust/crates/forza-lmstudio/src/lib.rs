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

pub use backend::LMStudioBackend;
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

    pub fn snapshot_id(prompt_id: &str) -> String {
        match get_system_prompt(prompt_id) {
            Some(text) => format!("{prompt_id}:{}", content_hash(text)),
            None => format!("{prompt_id}:missing"),
        }
    }
}
