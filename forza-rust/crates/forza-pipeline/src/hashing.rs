//! Content hashing: `sha256_hex + "_" + size`, matching `pipeline.image.file_hash`.

use std::path::Path;

use sha2::{Digest, Sha256};

use crate::error::PipelineError;

/// SHA-256 hex of bytes. Single owner for every ad-hoc `Sha256` use across
/// the workspace — hash new data here instead of spelling `Sha256` again.
#[must_use]
pub fn hash_bytes_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

/// SHA-256 hex of a file, streamed with buffered reads (never whole-file).
///
/// # Errors
///
/// Returns the underlying [`std::io::Error`] on open/read failures; callers
/// add their own context (e.g. [`PipelineError::HashFailed`]).
pub fn hash_file_hex(path: &Path) -> std::io::Result<String> {
    use std::io::BufReader;
    let file = std::fs::File::open(path)?;
    let mut reader = BufReader::with_capacity(64 * 1024, file);
    let mut hasher = Sha256::new();
    std::io::copy(&mut reader, &mut hasher)?;
    Ok(format!("{:x}", hasher.finalize()))
}

/// Hash a file with SHA-256 and return `(hex, size_bytes, format)`.
///
/// # Errors
///
/// Returns [`PipelineError::HashFailed`] when the file cannot be opened or
/// read (missing file, permissions, I/O failure mid-stream).
pub fn file_hash(path: &Path) -> Result<String, PipelineError> {
    let hex = hash_file_hex(path).map_err(|e| PipelineError::HashFailed {
        path: path.to_path_buf(),
        detail: e.to_string(),
    })?;
    let size = std::fs::metadata(path)
        .map_err(|e| PipelineError::HashFailed {
            path: path.to_path_buf(),
            detail: e.to_string(),
        })?
        .len();
    Ok(format!("{hex}_{size}"))
}
