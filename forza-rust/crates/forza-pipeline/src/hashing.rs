//! Content hashing: `sha256_hex + "_" + size`, matching `pipeline.image.file_hash`.

use std::io::Read;
use std::path::Path;

use sha2::{Digest, Sha256};

use crate::error::PipelineError;

pub fn file_hash(path: &Path) -> Result<String, PipelineError> {
    let mut file = std::fs::File::open(path).map_err(|e| PipelineError::HashFailed {
        path: path.to_path_buf(),
        detail: e.to_string(),
    })?;
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 8192];
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|e| PipelineError::HashFailed {
                path: path.to_path_buf(),
                detail: e.to_string(),
            })?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    let size = file
        .metadata()
        .map_err(|e| PipelineError::HashFailed {
            path: path.to_path_buf(),
            detail: e.to_string(),
        })?
        .len();
    Ok(format!("{:x}_{size}", hasher.finalize()))
}
