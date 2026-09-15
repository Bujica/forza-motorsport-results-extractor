Status: historical
Audience: developer, maintainer, LLM
Lifecycle: temporary (superseded by `migration_report.md` in this directory)
Scope: detailed porting analysis of `forza-rust/crates/forza-pipeline` crate
Last verified: 2026-08-27
Supersedes: none

# Detailed porting analysis — forza-pipeline

## Overview

Image discovery, hashing, metadata inspection, planning (duplicate detection), encoding (resize/desaturate/base64), naming sanitization. Ported from Python's `forza/pipeline/image.py` (365 lines) — the single Python module containing all pipeline image logic.

| File | Lines | Python Source | Port Status | Notes |
|------|-------|--------------|-------------|-------|
| `src/lib.rs` | 34 | Module-level exports + constants | **Fully ported** | Public API surface; re-exports all submodules |
| `src/discovery.rs` | 68 | `find_images`, `find_input_files` | **Fully ported** | `walkdir` replaces `rglob`; identical sorting/filtering |
| `src/hashing.rs` | 37 | `file_hash` | **Fully ported** | Exact SHA-256 hex + size format; chunked read matches Python |
| `src/metadata.rs` | 112 | `inspect_image_metadata` | **Partially ported** | Missing: timestamps (`file_modified_at`, etc.), raw image info dict (`image_metadata_json`) |
| `src/planning.rs` | 139 | `plan_images` + all dataclasses | **Fully ported** | All precedence paths reproduced; subtle Python semantics preserved in tests |
| `src/encoding.rs` | 144 | `encode_image`, `encode_image_payload`, `_desaturate_hsl_lightness` | **Fully ported** | Known divergence: WebP is lossless-only (Rust crate limitation) |
| `src/naming.rs` | 68 | `_safe_name`, `semantic_filename` | **Fully ported** | Identical sanitization pipeline; control chars handled equivalently |
| `src/error.rs` | 15 | `ImageEncodeError` + internal errors | **Fully ported** | Covers all error cases with `thiserror`; messages match Python patterns |
| `tests/pipeline_core.rs` | 217 | N/A (test suite) | **Fully tested** | 7 tests covering all major functions; validates exact Python semantics |

## src/lib.rs — Crate aggregate + public API surface

Python functionality ported: Module-level re-exports and the `SUPPORTED_IMAGE_EXTENSIONS` constant from `forza/pipeline/image.py`.

Status: **Fully ported**. This file is the crate's public API surface. It declares all submodules and re-exports their public items. The `SUPPORTED_IMAGE_EXTENSIONS` constant (`[".png", ".jpg", ".jpeg", ".webp"]`) matches the Python `frozenset`. The helper `is_supported_extension()` mirrors the Python `.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS` check (with case-insensitive dotted extension matching).

Key exports:
- All submodules: `discovery`, `encoding`, `error`, `hashing`, `metadata`, `naming`, `planning`
- Constants/types/functions re-exported from each submodule
- `SUPPORTED_IMAGE_EXTENSIONS` constant
- `is_supported_extension()` helper

## src/discovery.rs — Image file discovery

Python functionality ported: `find_images(root)` and `find_input_files(root)` from `forza/pipeline/image.py`.

Status: **Fully ported**. Both functions are complete equivalents:
- `find_input_files()` replaces Python's `root.rglob("*")` with Rust's `walkdir::WalkDir`, filtering for regular files and sorting by lowercase file name. The behavior is identical (Python uses `key=lambda path: path.name.lower()`, Rust uses the same via `to_lowercase()`).
- `find_images()` filters the full input list through `is_supported_extension()`, matching Python's `path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS`.

The test file confirms correct behavior: uppercase extensions (e.g., `.JPG`) are accepted, unsupported extensions (`.txt`) are excluded, and sorting is by lowercase name.

Key exports:
- `find_images(root: &Path) -> Vec<PathBuf>`
- `find_input_files(root: &Path) -> Vec<PathBuf>`

## src/hashing.rs — SHA-256 file hashing

Python functionality ported: `file_hash(path)` from `forza/pipeline/image.py`.

Status: **Fully ported**. The Rust implementation uses `sha2::Sha256` to compute the SHA-256 hex digest and appends `_` + file size, exactly matching Python's `f"{sha.hexdigest()}_{path.stat().st_size}"`. The chunked read (8192 bytes) mirrors Python's `fh.read(8192)` loop. Error handling wraps I/O failures into `PipelineError::HashFailed`, whereas Python raises `OSError` (caught by callers).

The test verifies the exact output format: `"b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9_11"` for `"hello world"`.

Key exports:
- `file_hash(path: &Path) -> Result<String, PipelineError>`

## src/metadata.rs — Image metadata inspection

Python functionality ported: `inspect_image_metadata(path)` from `forza/pipeline/image.py`.

Status: **Partially ported**. The Rust version captures the core metadata fields (`file_size_bytes`, `image_format`, `mime_type`, `width_px`, `height_px`, `color_mode`, `bit_depth`) but **omits several Python fields**:
- `file_modified_at` / `race_datetime` / `race_date` / `race_datetime_source` — the Rust struct has no timestamp fields. The comment notes "captured by callers via `fs::metadata`", meaning this is deferred to the caller layer rather than handled here.
- `image_metadata_json` (raw image info dict) — Python's `_json_safe_metadata(dict(img.info or {}))` is entirely absent from Rust.

The format detection differs slightly: Python uses `img.format or path.suffix.lstrip(".").upper()`, while Rust uses only the extension (`path.extension().to_uppercase()`), ignoring the decoded buffer layout. The MIME mapping and color mode / bit depth logic are equivalent.

Key exports:
- `ImageMetadataInfo` struct (7 fields)
- `inspect_metadata(path: &Path) -> Result<ImageMetadataInfo, PipelineError>`

## src/planning.rs — Image discovery planning + duplicate detection

Python functionality ported: `plan_images()`, all dataclasses (`DiscoveredImage`, `DuplicateImage`, `ExistingImage`, `SkippedImage`, `ImageDiscoveryPlan`), and the duplicate precedence logic from `forza/pipeline/image.py`.

Status: **Fully ported**. The Rust implementation faithfully reproduces Python's decision precedence:
1. Hash failure -> `SkippedImage` (reason `"hash_failed"`)
2. Path hash matches stored -> `ExistingImage`
3. Hash in known_hashes set -> `DuplicateImage` (reason `"cached"`)
4. Hash seen in batch -> `DuplicateImage` (reason `"batch"` with canonical name)
5. Otherwise -> `DiscoveredImage` (new unique)

The Rust version uses `KnownPathHashes = HashMap<String, String>` directly (simplifying Python's union of `set | Mapping`). The test file (`pipeline_core.rs`) explicitly validates all precedence paths including the subtle Python semantics: "seen_in_batch only registers NEW images, so an already-existing file never becomes the canonical of a batch duplicate."

Key exports:
- `DiscoveredImage`, `DuplicateImage`, `ExistingImage`, `SkippedImage` structs
- `ImageDiscoveryPlan` struct with `duplicate_count()` and `process_count()` methods
- `plan_images()` function
- `KnownPathHashes` type alias

## src/encoding.rs — Image encoding + base64 payload generation

Python functionality ported: `encode_image()`, `encode_image_payload()`, `_desaturate_hsl_lightness()`, and the `EncodedImage` dataclass from `forza/pipeline/image.py`.

Status: **Fully ported (with documented divergence)**. The encoding pipeline is complete:
- RGB conversion (`img.to_rgb8()` vs Python's `img.convert("RGB")`)
- LANCZOS downscale when width exceeds `max_width` (Rust uses `FilterType::Lanczos3`, Python uses `Image.Resampling.LANCZOS`)
- HSL lightness desaturation via per-pixel `(max + min) / 2` formula — Rust does this manually on pixel arrays, Python uses PIL's `ImageChops.lighter/darker/blend` (mathematically equivalent)
- Container encoding for PNG, JPEG (with quality), and WebP
- Base64 payload generation

**Documented divergence:** The comment notes that the pure-Rust `image` crate encodes lossless WebP only; the `encode_quality` parameter is ignored for WebP. Python's PIL supports lossy WebP encoding. This is a known limitation, not an omission.

The test verifies grayscale output (all pixels equal), resize dimensions, JPEG quality, and unsupported format rejection.

Key exports:
- `SUPPORTED_FORMATS` constant (`[(&str, &str)]`)
- `EncodedImage` struct (5 fields)
- `EncodeError` enum
- `encode_image_payload()` function
- `mime_for_format()` helper

## src/naming.rs — Semantic filename generation + sanitization

Python functionality ported: `_safe_name()`, `semantic_filename()` from `forza/pipeline/image.py`.

Status: **Fully ported**. The Rust version uses a hardcoded `FORBIDDEN_CHARS` array matching Python's `_FORBIDDEN_CHARS = '<>:"/\\|?*'`. The sanitization pipeline is identical:
- Remove forbidden characters
- Remove control characters (Python uses `re.sub(r"[\x00-\x1f]", "", clean)`, Rust uses `!c.is_control()`)
- Trim whitespace, strip trailing dots, cap at 150 chars

The test confirms exact behavior with forbidden chars (`Fuji: Speedway?` -> `Fuji Speedway`), control characters (`\x07` removed), empty fallback to `"Unknown"`, and length capping.

Key exports:
- `semantic_filename(track, race_class, suffix) -> String`

## src/error.rs — Pipeline error types

Python functionality ported: Error types from `forza/exceptions.py` (`ImageEncodeError`) and the pipeline's internal error handling.

Status: **Fully ported**. The Rust enum covers all pipeline error cases with `thiserror`:
- `HashFailed { path, detail }` — mirrors Python's OSError wrapping in callers
- `Encode { path, detail }` — mirrors Python's `ImageEncodeError` from `forza/exceptions.py`
- `UnsupportedFormat { format }` — mirrors Python's `ValueError` raised by `encode_image()`

The error messages match the Python patterns (e.g., `"failed to hash {path}: {detail}"`).

Key exports:
- `PipelineError` enum with 3 variants

## tests/pipeline_core.rs — End-to-end pipeline test coverage

Python functionality tested: End-to-end pipeline tests covering discovery, hashing, planning precedence, encoding, metadata inspection, and naming — the "Fase 6 deliverables" as noted in the doc comment.

Status: **Fully tested**. The test file exercises all major Rust crate functions with synthetic fixtures (`tempfile` + `image` crate):
- **Discovery:** Filters extensions, sorts by name
- **Hashing:** Verifies exact SHA-256 + size format against known value
- **Planning precedence:** Tests existing-by-path-hash, cached duplicates, batch duplicates, force mode, and hash failure skipping — explicitly validates the subtle Python semantics about `seen_in_batch` only registering NEW images
- **Encoding:** Verifies grayscale desaturation (all pixels equal), resize dimensions, JPEG quality, unsupported format rejection
- **Metadata:** Checks dimensions, format, MIME type, file size
- **Naming:** Validates exact output for known inputs

## Missing from Rust (not ported)

1. **`log_duplicate_skips()`** — Python's logging helper for duplicate skips is absent from the Rust crate entirely.
2. **Timestamp fields in metadata** — `file_modified_at`, `race_datetime`, `race_date`, `race_datetime_source` are not captured by `inspect_metadata`; deferred to callers per the comment.
3. **Raw image info dict** — Python's `_json_safe_metadata(dict(img.info or {}))` is omitted from Rust metadata inspection.
