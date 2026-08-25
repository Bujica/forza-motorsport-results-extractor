//! Text normalization helpers shared by calibration and reference matching.

use unicode_canonical_combining_class::{CanonicalCombiningClass, get_canonical_combining_class};
use unicode_normalization::UnicodeNormalization;

/// Collapse whitespace runs to single spaces, trim, and lowercase.
pub fn normalize_whitespace_lower(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    let mut in_space = false;
    for ch in value.chars() {
        if ch.is_whitespace() {
            in_space = !out.is_empty();
        } else {
            if in_space {
                out.push(' ');
                in_space = false;
            }
            out.extend(ch.to_lowercase());
        }
    }
    out
}

fn is_word_char(ch: char) -> bool {
    ch.is_alphanumeric() || ch == '_'
}

/// NFKD decompose, drop combining marks, lowercase, trim, and optionally
/// remove non-word characters entirely (mirrors `normalize_ascii_compare`).
pub fn normalize_ascii_compare(value: &str, spaces: bool) -> String {
    let nfkd: String = value.nfkd().collect();
    let mut text = String::with_capacity(nfkd.len());
    for ch in nfkd.chars() {
        if get_canonical_combining_class(ch) == CanonicalCombiningClass::NotReordered {
            text.extend(ch.to_lowercase());
        }
    }
    let trimmed = text.trim().to_string();
    if spaces {
        trimmed
    } else {
        trimmed.chars().filter(|c| is_word_char(*c)).collect()
    }
}

/// Read embedded/owned UTF-8 lines, trimming whitespace and dropping empties.
pub fn load_nonempty_lines_from_str(source: &str) -> Vec<String> {
    source
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .map(ToOwned::to_owned)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn whitespace_lower_collapses_runs() {
        assert_eq!(
            normalize_whitespace_lower("  Foo   BAR\tbaz "),
            "foo bar baz"
        );
        assert_eq!(normalize_whitespace_lower(""), "");
    }

    #[test]
    fn ascii_compare_drops_accents_and_case() {
        assert_eq!(
            normalize_ascii_compare("Nürburgring GP", true),
            "nurburgring gp"
        );
        assert_eq!(
            normalize_ascii_compare("Nürburgring-GP", false),
            "nurburgringgp"
        );
        assert_eq!(normalize_ascii_compare("ÁÉÍ", false), "aei");
    }

    #[test]
    fn lines_loader_trims_and_skips_empty() {
        assert_eq!(
            load_nonempty_lines_from_str("A\n\n  B  \nC"),
            vec!["A".to_string(), "B".to_string(), "C".to_string()]
        );
    }
}
