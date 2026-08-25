//! Deterministic import canonicalization for car names.

use std::collections::HashMap;

/// Result of canonicalizing one imported car name.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CarCanonicalizationResult {
    pub original: String,
    pub canonical: String,
    pub key: String,
    pub status: CarCanonicalizationStatus,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CarCanonicalizationStatus {
    Blank,
    AmbiguousCar,
    NewCar,
    CanonicalExact,
    CarAliasCanonicalized,
}

impl CarCanonicalizationStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Blank => "blank",
            Self::AmbiguousCar => "ambiguous_car",
            Self::NewCar => "new_car",
            Self::CanonicalExact => "canonical_exact",
            Self::CarAliasCanonicalized => "car_alias_canonicalized",
        }
    }
}

impl CarCanonicalizationResult {
    pub fn changed(&self) -> bool {
        self.original != self.canonical
    }
}

fn casefold(value: &str) -> String {
    value.to_lowercase()
}

/// Conservative matching key for Forza car names: punctuation/case/year
/// formatting variants collapse to the same key (`'74`, `1974`, `74`).
pub fn car_match_key(value: Option<&str>) -> String {
    let Some(value) = value else {
        return String::new();
    };
    if value.is_empty() {
        return String::new();
    }

    use unicode_normalization::UnicodeNormalization;
    let text: String = value.nfkc().collect();

    let text: String = text
        .chars()
        .map(|c| match c {
            '\u{2019}' | '\u{2018}' | '`' | '\u{B4}' | '\u{2B9}' => '\'',
            other => other,
        })
        .collect();
    let text = casefold(&text);

    let text = YEAR_FULL.replace_all(&text, "$1").into_owned();
    let text = QUOTED_YEAR.replace_all(&text, "$1$2").into_owned();
    let text = text.replace('\'', "");
    let text = NON_WORD.replace_all(&text, " ").into_owned();
    let text = SPACES.replace_all(&text, " ").into_owned();
    let text = text.trim().to_string();
    SPACE_BEFORE_YEAR.replace_all(&text, "$1$2").into_owned()
}

use std::sync::LazyLock;

/// Compile-once regex; patterns here are static and infallible.
macro_rules! lazy_regex {
    ($pattern:expr) => {
        LazyLock::new(|| match regex::Regex::new($pattern) {
            Ok(re) => re,
            Err(err) => panic!("invalid built-in regex: {err}"),
        })
    };
}

static YEAR_FULL: LazyLock<regex::Regex> = lazy_regex!(r"\b(?:19|20)(\d{2})\b");
static QUOTED_YEAR: LazyLock<regex::Regex> = lazy_regex!(r"(\s)'(\d{2})\b");
static NON_WORD: LazyLock<regex::Regex> = lazy_regex!(r"[^a-z0-9]+");
static SPACES: LazyLock<regex::Regex> = lazy_regex!(r"\s+");
static SPACE_BEFORE_YEAR: LazyLock<regex::Regex> = lazy_regex!(r"([a-z])\s+(\d{2})\b");

/// Unique-key map plus collision details for canonical car names.
pub fn car_canonical_map(
    canonical_cars: &[String],
) -> (HashMap<String, String>, HashMap<String, Vec<String>>) {
    let mut by_key: HashMap<String, Vec<String>> = HashMap::new();
    for name in canonical_cars {
        let clean = name.trim().to_string();
        if clean.is_empty() {
            continue;
        }
        let key = car_match_key(Some(&clean));
        if key.is_empty() {
            continue;
        }
        let entry = by_key.entry(key).or_default();
        if !entry.contains(&clean) {
            entry.push(clean);
        }
    }
    let collisions: HashMap<String, Vec<String>> = by_key
        .iter()
        .filter(|(_, names)| names.len() > 1)
        .map(|(k, names)| {
            let mut sorted = names.clone();
            sorted.sort();
            (k.clone(), sorted)
        })
        .collect();
    let unique: HashMap<String, String> = by_key
        .iter()
        .filter(|(_, names)| names.len() == 1)
        .map(|(k, names)| (k.clone(), names[0].clone()))
        .collect();
    (unique, collisions)
}

/// Canonicalize one imported car name via exact normalized-key matching.
/// Ambiguous keys are deliberately not rewritten.
pub fn canonicalize_car_name(
    value: Option<&str>,
    canonical_by_key: &HashMap<String, String>,
    collisions: Option<&HashMap<String, Vec<String>>>,
) -> CarCanonicalizationResult {
    let original = value.unwrap_or("").trim().to_string();
    let key = car_match_key(Some(original.as_str()));
    if key.is_empty() {
        return CarCanonicalizationResult {
            original: original.clone(),
            canonical: original,
            key,
            status: CarCanonicalizationStatus::Blank,
        };
    }
    if collisions.is_some_and(|c| c.contains_key(key.as_str())) {
        return CarCanonicalizationResult {
            original: original.clone(),
            canonical: original,
            key,
            status: CarCanonicalizationStatus::AmbiguousCar,
        };
    }
    match canonical_by_key.get(key.as_str()) {
        None => CarCanonicalizationResult {
            original: original.clone(),
            canonical: original,
            key,
            status: CarCanonicalizationStatus::NewCar,
        },
        Some(canonical) => {
            if *canonical == original {
                CarCanonicalizationResult {
                    original: original.clone(),
                    canonical: canonical.clone(),
                    key,
                    status: CarCanonicalizationStatus::CanonicalExact,
                }
            } else {
                CarCanonicalizationResult {
                    original: original.clone(),
                    canonical: canonical.clone(),
                    key,
                    status: CarCanonicalizationStatus::CarAliasCanonicalized,
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn year_variants_collapse() {
        assert_eq!(
            car_match_key(Some("Toyota Corolla '74")),
            car_match_key(Some("Toyota Corolla 1974"))
        );
        assert_eq!(car_match_key(Some("Elemental Rp1 ’19")), "elemental rp1 19");
        assert_eq!(car_match_key(Some("Mini Cooper `65")), "mini cooper65");
        assert_eq!(car_match_key(Some("Audi R8 LMS")), "audi r8 lms");
    }

    #[test]
    fn canonicalization_statuses() {
        let cars: Vec<String> = vec!["Audi R8 LMS".to_string(), "Audi R8".to_string()];
        let (unique, collisions) = car_canonical_map(&cars);
        assert!(collisions.is_empty());
        let r = canonicalize_car_name(Some("audi r8 lms"), &unique, Some(&collisions));
        assert_eq!(r.status.as_str(), "car_alias_canonicalized");
        assert_eq!(r.canonical, "Audi R8 LMS");
        let r = canonicalize_car_name(Some("Totally New Car"), &unique, Some(&collisions));
        assert_eq!(r.status.as_str(), "new_car");
        assert!(!r.changed());
    }
}
