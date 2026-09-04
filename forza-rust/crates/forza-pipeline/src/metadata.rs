//! Source-file metadata inspection (no mutation of the file).
//!
//! `file_modified_at` is the official race-date source for this project
//! (mirrors `pipeline.image.inspect_image_metadata`); file creation time is
//! intentionally not captured.

use std::path::Path;

use chrono::{DateTime, SecondsFormat, Utc};
use serde_json::json;

use crate::error::PipelineError;

/// Inspected source-file metadata (mirrors the Python `ImageMetadata`
/// read model). Datetimes are UTC SQLite strings, `race_date` is `YYYY-MM-DD`.
#[derive(Debug, Clone, PartialEq)]
pub struct ImageMetadataInfo {
    pub file_size_bytes: u64,
    pub image_format: String,
    pub mime_type: Option<String>,
    pub width_px: u32,
    pub height_px: u32,
    pub color_mode: String,
    pub bit_depth: Option<u32>,
    pub file_modified_at: Option<String>,
    pub race_datetime: Option<String>,
    pub race_date: Option<String>,
    pub race_datetime_source: String,
    /// Raw container metadata as a JSON object string (PIL-style info is not
    /// available under the `image` crate; buffer-layout facts are recorded).
    pub image_metadata_json: String,
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
    let reader = reader
        .with_guessed_format()
        .map_err(|e| PipelineError::Encode {
            path: path.to_path_buf(),
            detail: e.to_string(),
        })?;
    // Container truth first (like PIL's `img.format`): sniffed magic bytes,
    // falling back to the extension only when sniffing yields nothing.
    let detected = reader.format().map(container_format_name);
    let img = reader.decode().map_err(|e| PipelineError::Encode {
        path: path.to_path_buf(),
        detail: e.to_string(),
    })?;

    let format = detected.unwrap_or_else(|| guess_format_name(path, &img));
    let mime = mime_for(&format);
    let (width_px, height_px) = (img.width(), img.height());
    let color_mode = color_mode_name(img.color());
    let bit_depth = bits_per_pixel_estimate(&img);

    let file_modified_at: Option<String> = std::fs::metadata(path)
        .ok()
        .and_then(|m| m.modified().ok())
        .map(|modified| {
            let dt: DateTime<Utc> = modified.into();
            dt.to_rfc3339_opts(SecondsFormat::Secs, true)
        });
    // Python: race_datetime = race_date = file_modified_at (UTC).
    let race_date = file_modified_at.as_deref().map(|dt| dt[..10].to_string());

    let image_metadata_json = json!({
        "source": "image_crate_buffer_layout",
        "color_mode": color_mode,
        "bit_depth": bit_depth,
        "width_px": width_px,
        "height_px": height_px,
    })
    .to_string();

    Ok(ImageMetadataInfo {
        file_size_bytes: meta.len(),
        image_format: format,
        mime_type: mime,
        width_px,
        height_px,
        color_mode,
        bit_depth,
        file_modified_at: file_modified_at.clone(),
        race_datetime: file_modified_at,
        race_date,
        race_datetime_source: "file_modified_at".to_string(),
        image_metadata_json,
    })
}

/// Container format sniffed from magic bytes (PIL `img.format` parity).
fn container_format_name(format: image::ImageFormat) -> String {
    use image::ImageFormat as F;
    match format {
        F::Png => "PNG",
        F::Jpeg => "JPEG",
        F::WebP => "WEBP",
        F::Gif => "GIF",
        F::Bmp => "BMP",
        F::Tiff => "TIFF",
        _ => "PNG",
    }
    .to_string()
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
