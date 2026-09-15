//! Pipeline error type.

use std::path::PathBuf;

#[derive(Debug, thiserror::Error)]
pub enum PipelineError {
    #[error("failed to hash {path}: {detail}")]
    HashFailed { path: PathBuf, detail: String },

    #[error("failed to encode {path}: {detail}")]
    Encode { path: PathBuf, detail: String },

    #[error("unsupported image format '{format}'. Valid options: png, jpeg, webp")]
    UnsupportedFormat { format: String },
}
