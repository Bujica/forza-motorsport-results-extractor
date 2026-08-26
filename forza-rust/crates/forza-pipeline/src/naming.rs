//! Semantic filename generation (metadata-only; no filesystem access).

/// Characters Windows forbids in file names.
const FORBIDDEN_CHARS: &[char] = &['<', '>', ':', '"', '/', '\\', '|', '?', '*'];

fn safe_name(text: &str) -> String {
    let clean: String = text
        .chars()
        .filter(|c| !FORBIDDEN_CHARS.contains(c))
        .filter(|c| !c.is_control())
        .collect();
    clean
        .trim()
        .trim_end_matches('.')
        .chars()
        .take(150)
        .collect()
}

pub fn semantic_filename(track: &str, race_class: &str, suffix: &str) -> String {
    let track_part = {
        let s = safe_name(track);
        if s.is_empty() {
            "Unknown".to_string()
        } else {
            s
        }
    };
    let class_part = {
        let s = safe_name(race_class);
        if s.is_empty() {
            "Unknown".to_string()
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
            semantic_filename("Fuji: Speedway?", "A", ".png"),
            "Fuji Speedway - A.png"
        );
        assert_eq!(
            semantic_filename("Track\x07Bell", "B", ".png"),
            "TrackBell - B.png"
        );
    }

    #[test]
    fn empty_parts_fall_back_to_unknown() {
        assert_eq!(semantic_filename("", "", ".png"), "Unknown - Unknown.png");
    }

    #[test]
    fn trailing_dots_trimmed_and_long_names_capped() {
        assert_eq!(semantic_filename("Name...", "A", ".png"), "Name - A.png");
        let long = "x".repeat(300);
        let out = semantic_filename(&long, "A", ".png");
        assert!(out.chars().count() < 160);
    }
}
