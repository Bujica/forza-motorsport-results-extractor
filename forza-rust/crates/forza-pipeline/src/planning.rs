//! Duplicate handling and per-run planning. Ported from
//! `pipeline.image.plan_images` with the same precedence:
//! hash-failure -> existing-by-path-hash -> existing(set) -> cached duplicate
//! -> batch duplicate -> new unique.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use crate::error::PipelineError;
use crate::hashing::file_hash;

#[derive(Debug, Clone, PartialEq)]
pub struct DiscoveredImage {
    pub path: PathBuf,
    pub file_hash: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DuplicateImage {
    pub path: PathBuf,
    pub file_hash: String,
    /// `cached` (hash known to the database) or `batch` (repeated in this run).
    pub reason: String,
    pub canonical_name: String,
    pub duplicate_of_hash: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ExistingImage {
    pub path: PathBuf,
    pub file_hash: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct SkippedImage {
    pub path: PathBuf,
    pub reason: String,
    pub file_hash: Option<String>,
}

#[derive(Debug, Clone, Default)]
pub struct ImageDiscoveryPlan {
    pub total: usize,
    pub new_images: Vec<DiscoveredImage>,
    pub duplicates: Vec<DuplicateImage>,
    pub existing_images: Vec<ExistingImage>,
    pub skipped_images: Vec<SkippedImage>,
}

impl ImageDiscoveryPlan {
    pub fn duplicate_count(&self) -> usize {
        self.duplicates.len()
    }

    pub fn process_count(&self) -> usize {
        self.new_images.len()
    }
}

/// Map of current path -> stored hash for images already inventoried.
/// When a path's stored hash matches the on-disk hash the file is `existing`.
pub type KnownPathHashes = HashMap<String, String>;

#[allow(clippy::too_many_arguments)]
pub fn plan_images(
    all_images: &[PathBuf],
    known_hashes: &HashSet<String>,
    known_path_hashes: &KnownPathHashes,
    force: bool,
) -> Result<ImageDiscoveryPlan, PipelineError> {
    let mut plan = ImageDiscoveryPlan {
        total: all_images.len(),
        ..Default::default()
    };
    let mut seen_in_batch: HashMap<String, PathBuf> = HashMap::new();

    for path in all_images {
        let hash = match file_hash(path) {
            Ok(h) => h,
            Err(_) => {
                plan.skipped_images.push(SkippedImage {
                    path: path.clone(),
                    reason: "hash_failed".into(),
                    file_hash: None,
                });
                continue;
            }
        };

        if !force
            && known_path_hashes
                .get(&path_string(path))
                .is_some_and(|stored| *stored == hash)
        {
            plan.existing_images.push(ExistingImage {
                path: path.clone(),
                file_hash: hash,
            });
            continue;
        }

        if !force && known_hashes.contains(&hash) {
            plan.duplicates.push(DuplicateImage {
                path: path.clone(),
                file_hash: hash.clone(),
                reason: "cached".into(),
                canonical_name: String::new(),
                duplicate_of_hash: Some(hash),
            });
            continue;
        }

        if let Some(original) = seen_in_batch.get(&hash) {
            plan.duplicates.push(DuplicateImage {
                path: path.clone(),
                file_hash: hash.clone(),
                reason: "batch".into(),
                canonical_name: original
                    .file_name()
                    .map(|n| n.to_string_lossy().to_string())
                    .unwrap_or_default(),
                duplicate_of_hash: Some(hash),
            });
            continue;
        }

        seen_in_batch.insert(hash.clone(), path.clone());
        plan.new_images.push(DiscoveredImage {
            path: path.clone(),
            file_hash: hash,
        });
    }

    Ok(plan)
}

fn path_string(path: &Path) -> String {
    path.to_string_lossy().to_string()
}
