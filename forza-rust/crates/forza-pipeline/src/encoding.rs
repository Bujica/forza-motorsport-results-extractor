//! Encode a screenshot for the model request: RGB convert, optional
//! LANCZOS downscale, optional HSL-lightness desaturation, container encode,
//! base64 payload. Ported from `pipeline.image.encode_image_payload`.

use std::path::Path;

use base64::Engine as _;
use image::imageops::FilterType;

/// Container formats accepted in requests, with their MIME types.
pub const SUPPORTED_FORMATS: &[(&str, &str)] = &[
    ("jpeg", "image/jpeg"),
    ("png", "image/png"),
    ("webp", "image/webp"),
];

pub fn mime_for_format(format: &str) -> Option<&'static str> {
    let lower = format.to_lowercase();
    SUPPORTED_FORMATS
        .iter()
        .find(|(name, _)| *name == lower)
        .map(|(_, mime)| *mime)
}

#[derive(Debug, Clone, PartialEq)]
pub struct EncodedImage {
    pub data_b64: String,
    pub mime_type: String,
    pub format: String,
    pub width_px: u32,
    pub height_px: u32,
    /// Byte count of the encoded payload (not the base64 length).
    pub byte_count: usize,
}

#[derive(Debug, thiserror::Error)]
pub enum EncodeError {
    #[error("unsupported image format '{0}'. Valid options: png, jpeg, webp")]
    UnsupportedFormat(String),
    #[error("encode failed: {0}")]
    Io(String),
}

/// Encode `path` and return transport metadata for persistence.
///
/// Failures are operational errors; returning an empty payload is unsafe
/// because callers would send an invalid data URL to the model.
pub fn encode_image_payload(
    path: &Path,
    max_width: u32,
    encode_quality: u8,
    format: &str,
    grayscale: bool,
) -> Result<EncodedImage, EncodeError> {
    let fmt = format.to_lowercase();
    let Some(mime_static) = mime_for_format(&fmt) else {
        return Err(EncodeError::UnsupportedFormat(format.to_string()));
    };
    let mime = mime_static.to_string();

    let reader = image::ImageReader::open(path).map_err(|e| EncodeError::Io(e.to_string()))?;
    let img = reader
        .with_guessed_format()
        .map_err(|e| EncodeError::Io(e.to_string()))?
        .decode()
        .map_err(|e| EncodeError::Io(e.to_string()))?;

    let mut rgb = img.to_rgb8();
    if rgb.width() > max_width {
        let ratio = f64::from(max_width) / f64::from(rgb.width());
        let new_h = f64::from(rgb.height()) * ratio;
        let resized = image::DynamicImage::ImageRgb8(rgb).resize_exact(
            max_width,
            new_h.round() as u32,
            FilterType::Lanczos3,
        );
        rgb = resized.to_rgb8();
    }
    if grayscale {
        rgb = desaturate_hsl_lightness(&rgb);
    }

    let dynamic = image::DynamicImage::ImageRgb8(rgb);
    let mut buffer = std::io::Cursor::new(Vec::new());
    match fmt.as_str() {
        "png" => {
            use image::ImageEncoder as _;
            image::codecs::png::PngEncoder::new(&mut buffer)
                .write_image(
                    dynamic.as_bytes(),
                    dynamic.width(),
                    dynamic.height(),
                    dynamic.color().into(),
                )
                .map_err(|e| EncodeError::Io(e.to_string()))?;
        }
        "jpeg" => {
            use image::ImageEncoder as _;
            image::codecs::jpeg::JpegEncoder::new_with_quality(&mut buffer, encode_quality)
                .write_image(
                    dynamic.as_bytes(),
                    dynamic.width(),
                    dynamic.height(),
                    dynamic.color().into(),
                )
                .map_err(|e| EncodeError::Io(e.to_string()))?;
        }
        "webp" => {
            // The pure-Rust image crate encodes lossless webp only; quality is
            // ignored here (documented divergence from PIL's lossy quality).
            dynamic
                .write_to(&mut buffer, image::ImageFormat::WebP)
                .map_err(|e| EncodeError::Io(e.to_string()))?;
        }
        other => return Err(EncodeError::UnsupportedFormat(other.to_string())),
    }

    let bytes = buffer.into_inner();
    let (width_px, height_px) = {
        let decoded =
            image::load_from_memory(&bytes).map_err(|e| EncodeError::Io(e.to_string()))?;
        (decoded.width(), decoded.height())
    };
    Ok(EncodedImage {
        data_b64: base64::engine::general_purpose::STANDARD.encode(&bytes),
        mime_type: mime,
        format: fmt,
        width_px,
        height_px,
        byte_count: bytes.len(),
    })
}

/// HSL lightness per pixel: gray = (max(r,g,b) + min(r,g,b)) / 2.
fn desaturate_hsl_lightness(img: &image::RgbImage) -> image::RgbImage {
    let mut out = img.clone();
    for px in out.pixels_mut() {
        let max_ch = px[0].max(px[1]).max(px[2]);
        let min_ch = px[0].min(px[1]).min(px[2]);
        let gray = ((u16::from(max_ch) + u16::from(min_ch)) / 2) as u8;
        *px = image::Rgb([gray, gray, gray]);
    }
    out
}
