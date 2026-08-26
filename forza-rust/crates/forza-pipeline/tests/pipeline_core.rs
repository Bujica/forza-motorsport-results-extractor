// Fixture-driven pipeline tests: unwraps are the idiomatic helpers here.
#![allow(clippy::unwrap_used, clippy::expect_used)]

//! Pipeline tests with synthetic fixtures: discovery, hashing, planning
//! precedence, encoding, and naming — the Fase 6 deliverables.

use std::collections::{HashMap, HashSet};

use forza_pipeline::planning::KnownPathHashes;
use forza_pipeline::{encode_image_payload, find_images, plan_images, semantic_filename};

fn write_png(path: &std::path::Path, width: u32, height: u32, color: [u8; 3]) {
    let img = image::RgbImage::from_fn(width, height, |_, _| image::Rgb(color));
    img.save_with_format(path, image::ImageFormat::Png).unwrap();
}

fn setup_inputs() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    std::fs::create_dir(root.join("sub")).unwrap();

    // unique A, unique B, batch duplicate of A, unsupported ext
    write_png(&root.join("shot_a.png"), 64, 64, [200, 10, 10]);
    write_png(&root.join("shot_b.png"), 64, 64, [10, 200, 10]);
    write_png(
        &root.join("sub").join("shot_a_copy.png"),
        64,
        64,
        [200, 10, 10],
    );
    std::fs::write(root.join("notes.txt"), b"not an image").unwrap();
    dir
}

#[test]
fn discovery_finds_only_supported_images_sorted() {
    let dir = setup_inputs();
    let images = find_images(dir.path());
    let names: Vec<String> = images
        .iter()
        .map(|p| p.file_name().unwrap().to_string_lossy().to_string())
        .collect();
    assert_eq!(names, vec!["shot_a.png", "shot_a_copy.png", "shot_b.png"]);
}

#[test]
fn file_hash_matches_known_sha256_size_format() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("blob.bin");
    std::fs::write(&path, b"hello world").unwrap();

    let got = forza_pipeline::file_hash(&path).unwrap();
    // sha256("hello world") = b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9
    assert_eq!(
        got,
        "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9_11"
    );
}

#[test]
fn planning_precedence_new_cached_batch_existing_force() {
    let dir = setup_inputs();
    let images = find_images(dir.path());
    let hash_of = |p: &std::path::Path| forza_pipeline::file_hash(p).unwrap();

    let shot_a = images
        .iter()
        .find(|p| p.file_name().unwrap() == "shot_a.png")
        .unwrap();
    let shot_b = images
        .iter()
        .find(|p| p.file_name().unwrap() == "shot_b.png")
        .unwrap();

    // Database already knows shot_a by path+hash -> existing.
    let mut known_paths: KnownPathHashes = HashMap::new();
    known_paths.insert(shot_a.to_string_lossy().to_string(), hash_of(shot_a));

    // Database knows some unrelated hash -> nothing cached; batch dedup still applies.
    let mut known_hashes = HashSet::new();
    known_hashes.insert("deadbeef_1".to_string());

    let plan = plan_images(&images, &known_hashes, &known_paths, false).unwrap();

    assert_eq!(plan.total, 3);
    assert_eq!(plan.existing_images.len(), 1);
    assert_eq!(plan.existing_images[0].file_hash, hash_of(shot_a));

    let new_names: Vec<String> = plan
        .new_images
        .iter()
        .map(|d| d.path.file_name().unwrap().to_string_lossy().to_string())
        .collect();
    assert_eq!(new_names.len(), 2, "b + a_copy are new");
    assert!(new_names.contains(&"shot_b.png".to_string()));

    // Python semantics: seen_in_batch only registers NEW images, so an
    // already-existing file never becomes the canonical of a batch duplicate.
    assert_eq!(plan.duplicates.len(), 0);

    // Without path knowledge both copies are new on first sight and the
    // second occurrence becomes a batch duplicate of the first.
    let plan_fresh = plan_images(&images, &HashSet::new(), &KnownPathHashes::new(), false).unwrap();
    assert_eq!(plan_fresh.process_count(), 2);
    let batch: Vec<_> = plan_fresh
        .duplicates
        .iter()
        .filter(|d| d.reason == "batch")
        .collect();
    assert_eq!(batch.len(), 1);
    assert_eq!(batch[0].canonical_name, "shot_a.png");

    // Cached duplicates: mark a's hash as known -> both a files become cached dup / existing stays.
    let mut known_hashes2 = known_hashes.clone();
    known_hashes2.insert(hash_of(shot_a));
    known_hashes2.insert(hash_of(shot_b));
    let plan2 = plan_images(&images, &known_hashes2, &known_paths, false).unwrap();
    let cached: Vec<_> = plan2
        .duplicates
        .iter()
        .filter(|d| d.reason == "cached")
        .collect();
    assert_eq!(cached.len(), 2, "{:?}", plan2.duplicates);

    // force ignores existing/cached knowledge entirely.
    let forced = plan_images(&images, &known_hashes2, &known_paths, true).unwrap();
    assert_eq!(forced.process_count(), 2);
    assert_eq!(forced.duplicate_count(), 1); // only in-batch repetition remains
    assert!(forced.existing_images.is_empty());
}

#[test]
fn hash_failure_is_recorded_per_file_without_aborting_the_batch() {
    let dir = tempfile::tempdir().unwrap();
    let ghost = dir.path().join("ghost.png"); // listed but not on disk
    let real = dir.path().join("real.png");
    write_png(&real, 16, 16, [1, 2, 3]);

    let images = vec![ghost.clone(), real];
    let plan = plan_images(&images, &HashSet::new(), &KnownPathHashes::new(), false).unwrap();

    assert_eq!(plan.total, 2);
    assert_eq!(
        plan.skipped_images,
        vec![forza_pipeline::SkippedImage {
            path: ghost,
            reason: "hash_failed".into(),
            file_hash: None,
        }]
    );
    assert_eq!(plan.process_count(), 1);
}

#[test]
fn encoding_resizes_desaturates_and_reports_payload_bytes() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("big_color.png");

    // 100x50 saturated gradient-ish image.
    let img = image::RgbImage::from_fn(100, 50, |x, _| image::Rgb([(x % 255) as u8, 30, 220]));
    img.save_with_format(&path, image::ImageFormat::Png)
        .unwrap();

    // PNG grayscale path.
    let encoded_png = encode_image_payload(&path, 1600, 85, "png", true).unwrap();
    assert_eq!(encoded_png.mime_type, "image/png");
    assert_eq!((encoded_png.width_px, encoded_png.height_px), (100, 50));
    assert!(encoded_png.byte_count > 0);

    use base64::Engine as _;
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(encoded_png.data_b64.as_bytes())
        .unwrap();
    let decoded = image::load_from_memory(&bytes).unwrap();
    for px in decoded.to_rgb8().pixels() {
        assert_eq!(px[0], px[1]);
        assert_eq!(px[1], px[2], "desaturated pixels must be gray");
    }

    // Resize path: max_width below current width.
    let small = encode_image_payload(&path, 40, 85, "png", false).unwrap();
    assert_eq!((small.width_px, small.height_px), (40, 20));

    // JPEG honors quality parameter and mime.
    let jpeg = encode_image_payload(&path, 1600, 60, "jpeg", true).unwrap();
    assert_eq!(jpeg.mime_type, "image/jpeg");
    assert!(jpeg.byte_count > 0);

    // Unsupported format rejected before touching the file.
    let err = encode_image_payload(&path, 1600, 85, "bmp", true).unwrap_err();
    assert!(err.to_string().contains("unsupported image format"));
}

#[test]
fn metadata_inspection_reports_dimensions_and_mime() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("meta.png");
    write_png(&path, 320, 240, [9, 9, 9]);

    let meta = forza_pipeline::inspect_metadata(&path).unwrap();
    assert_eq!(meta.width_px, 320);
    assert_eq!(meta.height_px, 240);
    assert_eq!(meta.image_format, "PNG");
    assert_eq!(meta.mime_type.as_deref(), Some("image/png"));
    assert_eq!(
        meta.file_size_bytes,
        std::fs::metadata(&path).unwrap().len()
    );
}

#[test]
fn semantic_naming_matches_python_examples() {
    assert_eq!(
        semantic_filename("Fuji Speedway", "A", ".png"),
        "Fuji Speedway - A.png"
    );
}
