//! LLM error types.

#[derive(Debug, thiserror::Error)]
pub enum LlmError {
    #[error("transport error: {0}")]
    Transport(String),

    #[error("LM Studio returned HTTP {status}")]
    Http { status: u16 },

    #[error("runtime not ready: {0}")]
    Runtime(String),

    #[error("parse error: {0}")]
    Parse(String),

    #[error("all {} adaptive attempt(s) failed", attempts.len())]
    Exhausted { attempts: Vec<ModelAttemptRecord> },
}

use crate::protocol::ModelAttemptRecord;
