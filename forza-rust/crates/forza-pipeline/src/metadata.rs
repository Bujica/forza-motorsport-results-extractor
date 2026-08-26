//! Source-file metadata inspection (no mutation of the file).

use std::path::Path;

use crate::error::PipelineError;

#[derive(Debug, Clone, PartialEq)]
pub struct ImageMetadataInfo {
    pub file_size_bytes: u64,
    pub image_format: String,
    pub mime_type: Option<String>,
    pub width_px: u32,
    pub height_px: u32,
    pub color_mode: String,
    pub bit_depth: Option<u32>,
}

/// Inspect the physical file; `file_modified_at` stays the official race-date
/// source in this project (captured by callers via `fs::metadata`).
pub fn inspect_metadata(path: &Path) -> Result<ImageMetadataInfo, PipelineError> {
    let meta = std::fs::metadata(path).map_err(|e| PipelineError::Encode {
        path: path.to_path_buf(),
        detail: e.to_string(),
    })?;

    let reader = image::ImageReader::open(path).map_err(|e| PipelineError::Encode {
        path: path.to_path_buf(),
        detail: e.to_string(),
    })?;
    let img = reader
        .with_guessed_format()
        .map_err(|e| PipelineError::Encode {
            path: path.to_path_buf(),
            detail: e.to_string(),
        })?
        .decode()
        .map_err(|e| PipelineError::Encode {
            path: path.to_path_buf(),
            detail: e.to_string(),
        })?;

    let format = guess_format_name(path, &img);
    let mime = mime_for(&format);
    let (width_px, height_px) = (img.width(), img.height());
    let color_mode = color_mode_name(img.color());
    let bit_depth = bits_per_pixel_estimate(&img);

    Ok(ImageMetadataInfo {
        file_size_bytes: meta.len(),
        image_format: format,
        mime_type: mime,
        width_px,
        height_px,
        color_mode,
        bit_depth,
    })
}

fn guess_format_name(path: &Path, img: &image::DynamicImage) -> String {
    // The `image` crate reports the decoded buffer layout; the container
    // format comes from the extension for our supported set.
    let ext = path
        .extension()
        .map(|e| e.to_string_lossy().to_uppercase())
        .unwrap_or_else(|| "PNG".into());
    let _ = img;
    ext
}

fn mime_for(format_upper: &str) -> Option<String> {
    match format_upper {
        "JPEG" | "JPG" => Some("image/jpeg".into()),
        "PNG" => Some("image/png".into()),
        "WEBP" => Some("image/webp".into()),
        _ => None,
    }
}

fn color_mode_name(color: image::ColorType) -> String {
    match color {
        image::ColorType::L8 => "L",
        image::ColorType::La8 => "LA",
        image::ColorType::Rgb8 => "RGB",
        image::ColorType::Rgba8 => "RGBA",
        image::ColorType::L16 => "I;16",
        image::ColorType::La16 => "LA16",
        image::ColorType::Rgb16 => "RGB16",
        image::ColorType::Rgba16 => "RGBA16",
        image::ColorType::Rgb32F => "RGB32F",
        image::ColorType::Rgba32F => "RGBA32F",
        _ => "RGB",
    }
    .to_string()
}

fn bits_per_pixel_estimate(img: &image::DynamicImage) -> Option<u32> {
    use image::ColorType as C;
    let bits = match img.color() {
        C::L8 => 8,
        C::La8 => 16,
        C::Rgb8 => 24,
        C::Rgba8 => 32,
        C::L16 => 16,
        C::La16 => 32,
        C::Rgb16 => 48,
        C::Rgba16 => 64,
        C::Rgb32F => 96,
        C::Rgba32F => 128,
        _ => 24,
    };
    Some(bits)
}
