// Inline tests exercise fallible filesystem helpers directly.
#![cfg_attr(test, allow(clippy::unwrap_used))]

//! Discovery of input files, sorted by lowercase file name.

use std::path::{Path, PathBuf};

/// Every supported image below `root` (recursive), sorted by name.
pub fn find_images(root: &Path) -> Vec<PathBuf> {
    find_input_files(root)
        .into_iter()
        .filter(|path| crate::is_supported_extension(path))
        .collect()
}

/// Every regular file considered by a run (recursive), sorted by name.
pub fn find_input_files(root: &Path) -> Vec<PathBuf> {
    if !root.exists() {
        return Vec::new();
    }
    let mut files: Vec<PathBuf> = walkdir::WalkDir::new(root)
        .follow_links(false)
        .into_iter()
        .filter_map(|entry| entry.ok())
        .filter(|entry| entry.file_type().is_file())
        .map(|entry| entry.into_path())
        .collect();
    files.sort_by_key(|path| {
        path.file_name()
            .map(|n| n.to_string_lossy().to_lowercase())
            .unwrap_or_default()
    });
    files
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn discovery_filters_extensions_and_sorts_by_name() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path();

        std::fs::write(root.join("b.png"), b"png").unwrap();
        std::fs::write(root.join("A.JPG"), b"jpg").unwrap(); // uppercase ext
        std::fs::write(root.join("c.webp"), b"webp").unwrap();
        std::fs::write(root.join("notes.txt"), b"text").unwrap();
        std::fs::create_dir(root.join("sub")).unwrap();
        std::fs::write(root.join("sub").join("a.png"), b"png2").unwrap();

        let images = find_images(root);
        let names: Vec<String> = images
            .iter()
            .map(|p| p.file_name().unwrap().to_string_lossy().to_string())
            .collect();
        // Python sorts by name.lower(): "a.jpg" < "a.png".
        assert_eq!(names, vec!["A.JPG", "a.png", "b.png", "c.webp"]);

        let all = find_input_files(root);
        assert_eq!(all.len(), 5, "txt included in full input listing");
    }

    #[test]
    fn missing_root_yields_empty_plan_inputs() {
        assert!(find_images(Path::new("Z:/definitely/not/here")).is_empty());
    }
}
