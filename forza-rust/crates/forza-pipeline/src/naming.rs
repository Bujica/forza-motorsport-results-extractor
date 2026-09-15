//! Semantic filename generation (metadata-only; no filesystem access).

use forza_domain::enums::RaceClass;

/// Characters Windows forbids in file names. Single owner: the rename flow
/// in `forza-app` sanitizes through [`sanitize_filename_stem`] instead of
/// retyping this list.
pub const WIN_FORBIDDEN_CHARS: &[char] = &['<', '>', ':', '"', '/', '\\', '|', '?', '*'];

/// Windows device names that cannot be file stems even with an extension.
pub const WIN_RESERVED_NAMES: &[&str] = &[
    "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8",
    "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
];

/// Knobs for [`sanitize_filename_stem`]. The two call sites intentionally
/// differ (inventory parts vs. on-disk renames); the options make the
/// difference explicit instead of a second implementation.
pub struct SanitizeOptions {
    /// Max stem chars kept (suffixes are handled by the caller).
    pub max_chars: usize,
    /// Collapse internal whitespace runs (`"a   b"` → `"a b"`).
    pub collapse_whitespace: bool,
    /// Append `_` when the stem is a reserved device name.
    pub guard_reserved: bool,
}

/// Options for finished file names on disk (see `image_rename`).
pub const FILE_NAME_OPTS: SanitizeOptions = SanitizeOptions {
    max_chars: 200,
    collapse_whitespace: true,
    guard_reserved: true,
};

/// Options for `"Track - Class"` inventory parts ([`semantic_filename`]).
const INVENTORY_PART_OPTS: SanitizeOptions = SanitizeOptions {
    max_chars: 150,
    collapse_whitespace: false,
    guard_reserved: false,
};

/// Windows-safe stem shared by inventory names and file renames.
#[must_use]
pub fn sanitize_filename_stem(stem: &str, opts: &SanitizeOptions) -> String {
    let mut clean: String = stem
        .chars()
        .filter(|c| !WIN_FORBIDDEN_CHARS.contains(c))
        .filter(|c| !c.is_control())
        .collect();
    if opts.collapse_whitespace {
        clean = clean
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ")
            .trim()
            .trim_end_matches('.')
            .to_string();
    } else {
        clean = clean.trim().trim_end_matches('.').to_string();
    }
    if opts.guard_reserved && WIN_RESERVED_NAMES.contains(&clean.to_uppercase().as_str()) {
        clean.push('_');
    }
    clean.chars().take(opts.max_chars).collect()
}

fn safe_name(text: &str) -> String {
    sanitize_filename_stem(text, &INVENTORY_PART_OPTS)
}

/// Build the `"{track} - {class}{suffix}"` inventory name.
///
/// Takes the unified [`RaceClass`] so a new class cannot silently render as an
/// empty or fallback string in renamed files.
///
/// # Examples
///
/// ```
/// use forza_domain::enums::RaceClass;
/// use forza_pipeline::semantic_filename;
///
/// assert_eq!(
///     semantic_filename("Fuji Speedway", RaceClass::A, ".png"),
///     "Fuji Speedway - A.png"
/// );
/// ```
pub fn semantic_filename(track: &str, race_class: RaceClass, suffix: &str) -> String {
    let track_part = {
        let s = safe_name(track);
        if s.is_empty() {
            RaceClass::Unknown.as_str().to_string()
        } else {
            s
        }
    };
    let class_part = {
        let s = safe_name(race_class.as_str());
        if s.is_empty() {
            RaceClass::Unknown.as_str().to_string()
        } else {
            s
        }
    };
    format!("{track_part} - {class_part}{suffix}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sanitizes_forbidden_and_control_chars() {
        assert_eq!(
            semantic_filename("Fuji: Speedway?", RaceClass::A, ".png"),
            "Fuji Speedway - A.png"
        );
        assert_eq!(
            semantic_filename("Track\x07Bell", RaceClass::B, ".png"),
            "TrackBell - B.png"
        );
    }

    #[test]
    fn empty_parts_fall_back_to_unknown() {
        assert_eq!(
            semantic_filename("", RaceClass::Unknown, ".png"),
            "Unknown - Unknown.png"
        );
    }

    #[test]
    fn trailing_dots_trimmed_and_long_names_capped() {
        assert_eq!(
            semantic_filename("Name...", RaceClass::A, ".png"),
            "Name - A.png"
        );
        let long = "x".repeat(300);
        let out = semantic_filename(&long, RaceClass::A, ".png");
        assert!(out.chars().count() < 160);
    }
}
