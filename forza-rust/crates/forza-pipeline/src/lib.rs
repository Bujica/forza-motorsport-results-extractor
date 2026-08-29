//! Filesystem, image processing, and per-input planning (migration §4.4).
//!
//! Ported from `forza/pipeline/image.py`; decision vocabularies match the
//! persisted `run_inputs.decision` contract.

pub mod discovery;
pub mod encoding;
pub mod error;
pub mod hashing;
pub mod metadata;
pub mod naming;
pub mod planning;

pub use discovery::{find_images, find_input_files};
pub use encoding::{EncodeError, EncodedImage, SUPPORTED_FORMATS, encode_image_payload};
pub use error::PipelineError;
pub use hashing::file_hash;
pub use metadata::{ImageMetadataInfo, inspect_metadata};
pub use naming::semantic_filename;
pub use planning::{
    DiscoveredImage, DuplicateImage, ExistingImage, ImageDiscoveryPlan, SkippedImage,
    log_duplicate_skips, plan_images,
};

/// Extensions accepted as processable screenshots.
pub const SUPPORTED_IMAGE_EXTENSIONS: &[&str] = &[".png", ".jpg", ".jpeg", ".webp"];

pub fn is_supported_extension(path: &std::path::Path) -> bool {
    path.extension()
        .map(|ext| {
            let dotted = format!(".{}", ext.to_string_lossy().to_lowercase());
            SUPPORTED_IMAGE_EXTENSIONS.contains(&dotted.as_str())
        })
        .unwrap_or(false)
}
