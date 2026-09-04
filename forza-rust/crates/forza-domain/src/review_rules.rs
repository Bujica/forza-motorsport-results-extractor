//! Review-case trigger detection and track suggestions.

use regex::Regex;
use std::sync::LazyLock;

macro_rules! lazy_regex {
    ($pattern:expr) => {
        LazyLock::new(|| match Regex::new($pattern) {
            Ok(re) => re,
            Err(err) => panic!("invalid built-in regex: {err}"),
        })
    };
}

static SUSPICIOUS_SYMBOL: LazyLock<Regex> = lazy_regex!(r"[^\w\s.\-']");
static NUMERIC_PREFIX: LazyLock<Regex> = lazy_regex!(r"^\s*\d{1,3}[\s_\-.].+");
static AMBIGUOUS_LAYOUT: LazyLock<Regex> = lazy_regex!(r"(?i)ambiguous layout\)?\s*:\s*(.+)$");
/// True when the driver name contains characters outside the allowed set.
pub fn has_suspicious_name_symbol(value: &str) -> bool {
    SUSPICIOUS_SYMBOL.is_match(value)
}

/// True when the driver name starts with a 1-3 digit prefix.
pub fn has_numeric_name_prefix(value: &str) -> bool {
    NUMERIC_PREFIX.is_match(value)
}

/// Review trigger for a driver name, mirroring Python's reason strings.
pub fn driver_name_review_trigger(value: Option<&str>) -> Option<&'static str> {
    let raw = value.unwrap_or("");
    if raw.trim().is_empty() {
        return Some("driver_name_empty");
    }
    if has_numeric_name_prefix(raw) {
        return Some("numeric_prefix");
    }
    if has_suspicious_name_symbol(raw) {
        return Some("invalid_symbol");
    }
    None
}

/// Extract the raw portion of an `"ambiguous layout: RAW"` marker string.
pub fn ambiguous_raw_track(track: Option<&str>) -> String {
    match AMBIGUOUS_LAYOUT.captures(track.unwrap_or("")) {
        Some(caps) => caps
            .get(1)
            .map(|m| m.as_str().trim().to_string())
            .unwrap_or_default(),
        None => String::new(),
    }
}

fn review_track_key(text: &str) -> String {
    use unicode_canonical_combining_class::{
        CanonicalCombiningClass, get_canonical_combining_class as ccc,
    };
    use unicode_normalization::UnicodeNormalization;
    let nfkd: String = text.nfkd().collect();
    // Full `to_lowercase` like Python's `.lower()` (not ASCII-only): the
    // downstream filter keeps ASCII alphanumerics either way, but this stays
    // correct if the filter ever widens to Unicode.
    let clean: String = nfkd
        .chars()
        .filter(|ch| ccc(*ch) == CanonicalCombiningClass::NotReordered)
        .flat_map(|ch| ch.to_lowercase())
        .collect();
    let mut out = String::with_capacity(clean.len());
    let mut pending_sep = false;
    for ch in clean.chars() {
        if ch.is_ascii_lowercase() || ch.is_ascii_digit() {
            if pending_sep {
                out.push(' ');
                pending_sep = false;
            }
            out.push(ch);
        } else {
            pending_sep = !out.is_empty();
        }
    }
    out
}

/// Known tracks whose normalized key starts with the ambiguous raw key,
/// capped at 8 suggestions like the Python contract.
pub fn track_suggestions(track: &str, known_tracks: &[String]) -> Vec<String> {
    let raw = ambiguous_raw_track(Some(track));
    if raw.is_empty() {
        return Vec::new();
    }
    let raw_key = review_track_key(&raw);
    if raw_key.is_empty() {
        return Vec::new();
    }
    known_tracks
        .iter()
        .filter(|candidate| review_track_key(candidate).starts_with(raw_key.as_str()))
        .take(8)
        .cloned()
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn triggers_follow_python_reason_strings() {
        assert_eq!(
            driver_name_review_trigger(Some("   ")),
            Some("driver_name_empty")
        );
        assert_eq!(
            driver_name_review_trigger(Some("12 Fast")),
            Some("numeric_prefix")
        );
        assert_eq!(
            driver_name_review_trigger(Some("Bad★Name")),
            Some("invalid_symbol")
        );
        assert_eq!(driver_name_review_trigger(Some("Good Name-1.")), None);
    }

    #[test]
    fn ambiguous_marker_extraction_and_suggestions() {
        assert_eq!(
            ambiguous_raw_track(Some("Ambiguous layout: Le Mans")),
            "Le Mans"
        );
        let known: Vec<String> = vec![
            "Le Mans Full Circuit".to_string(),
            "Le Mans Old Mulsanne Circuit".to_string(),
            "Fuji Speedway".to_string(),
        ];
        let got = track_suggestions("ambiguous layout: le mans", &known);
        assert_eq!(got.len(), 2);
    }

    #[test]
    fn suggestion_cap_is_eight() {
        let known: Vec<String> = (0..20).map(|i| format!("Circuit {i}")).collect();
        let got = track_suggestions("ambiguous layout: Circuit", &known);
        assert_eq!(got.len(), 8);
    }
}
